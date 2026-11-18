"""
Avaliação dos modelos no teste (OE2).

Para cada predição salva calcula MAE e RMSE em núcleos, o ganho sobre a
persistência (repetir o valor atual), o atraso estimado da predição e
spikes-precision/recall. Pico segue Agulló et al. (2025), com sigma = 2 e
gamma = 250; um pico real conta como antecipado se houver pico previsto entre
h passos antes e 1 passo depois dele.

Saídas: resultados/oe2_metricas.csv e resultados/picos_<modelo>_<perfil>_h<H>.csv

Uso: python modelos/avaliacao.py [--pico percentil] [--eventos pontos]
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

SIGMA, GAMMA = 2.0, 250      # Agulló et al. (2025)
PERCENTIL = 95


def picos_agullo(y: np.ndarray, sigma: float = SIGMA, gamma: int = GAMMA) -> np.ndarray:
    # pico em k se y[k] - média(janela anterior) > sigma * desvio(janela anterior)
    s = pd.Series(y)
    media = s.shift(1).rolling(gamma, min_periods=10).mean()
    desvio = s.shift(1).rolling(gamma, min_periods=10).std()
    return ((s - media) > sigma * desvio).fillna(False).to_numpy()


DELTA = 1   # tolerância depois do pico real, em passos


def inicios_de_eventos(flag: np.ndarray) -> np.ndarray:
    # pontos marcados em sequência viram um evento, representado pelo primeiro
    f = np.asarray(flag, dtype=bool)
    inicio = f & ~np.r_[False, f[:-1]]
    return inicio


def precisao_revocacao(real: np.ndarray, prev: np.ndarray, tau: int, delta: int = DELTA):
    # previsto em p casa com real em r se r - tau <= p <= r + delta
    idx_r, idx_p = np.flatnonzero(real), np.flatnonzero(prev)
    if len(idx_p) == 0 or len(idx_r) == 0:
        return 0.0, 0.0, len(idx_r), len(idx_p)
    casa = lambda p, r: (r - tau <= p) & (p <= r + delta)
    acertos_p = sum(np.any(casa(p, idx_r)) for p in idx_p)
    detect_r = sum(np.any(casa(idx_p, r)) for r in idx_r)
    return acertos_p / len(idx_p), detect_r / len(idx_r), len(idx_r), len(idx_p)


def atraso_estimado(prev: np.ndarray, serie: np.ndarray, pos: np.ndarray, h: int) -> int:
    # deslocamento k que melhor alinha previsto e real; persistência dá k = h
    melhor_k, melhor_r = 0, -np.inf
    for k in range(0, h + 1):
        r = np.corrcoef(prev, serie[pos - k])[0, 1]
        if r > melhor_r:
            melhor_k, melhor_r = k, r
    return melhor_k


def janela_comum(arquivos) -> dict:
    # a LSTM perde mais pontos no início do teste que o XGBoost (lookback maior);
    # usa o menor tamanho de cada (perfil, horizonte) para comparar no mesmo trecho
    n = {}
    for arq in arquivos:
        _, _, perfil, hor = arq.stem.split("_")
        tam = len(pd.read_csv(arq))
        n[(perfil, hor)] = min(n.get((perfil, hor), tam), tam)
    return n


def ler_predicoes(arq: Path, n: int) -> pd.DataFrame:
    # os alvos ocupam as últimas posições do teste, então corta pelo início
    return pd.read_csv(arq).tail(n).reset_index(drop=True)


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--pico", choices=["agullo", "percentil"], default="agullo")
    ap.add_argument("--eventos", choices=["inicios", "pontos"], default="inicios",
                    help="inicios: cada sequência de pontos é um evento (padrão); pontos: ponto a ponto")
    args = ap.parse_args()

    arquivos = sorted(Path("resultados").glob("pred_*.csv"))
    if not arquivos:
        print("Nenhum resultados/pred_*.csv - rode os treinos antes.")
        return
    n_comum = janela_comum(arquivos)
    linhas = []
    for arq in arquivos:
        _, modelo, perfil, hor = arq.stem.split("_")
        h = int(hor[1:])
        d = np.load(f"dados/preparados_{perfil}.npz", allow_pickle=True)
        minimo, amp = float(d["minimo"][0]), float(d["amplitude"][0])

        df = ler_predicoes(arq, n_comum[(perfil, hor)])
        real_n, prev_n = df["real"].to_numpy(), df["previsto"].to_numpy()
        real, prev = real_n * amp + minimo, prev_n * amp + minimo

        mae = float(np.mean(np.abs(real - prev)))
        rmse = float(np.sqrt(np.mean((real - prev) ** 2)))

        # os alvos ocupam as últimas posições da série de teste
        serie = d["teste"][:, 0] * amp + minimo
        pos = np.arange(len(serie) - len(real), len(serie))
        persist = serie[pos - h]
        mae_persist = float(np.mean(np.abs(real - persist)))
        ganho = 100 * (1 - mae / mae_persist) if mae_persist > 0 else float("nan")
        k = atraso_estimado(prev, serie, pos, h)

        if args.pico == "agullo":
            pico_real, pico_prev = picos_agullo(real), picos_agullo(prev)
        else:
            limiar = np.percentile(d["treino"][:, 0] * amp + minimo, PERCENTIL)
            pico_real, pico_prev = real >= limiar, prev >= limiar
        if args.eventos == "inicios":
            ev_real, ev_prev = inicios_de_eventos(pico_real), inicios_de_eventos(pico_prev)
        else:
            ev_real, ev_prev = pico_real, pico_prev
        prec, rev, n_real, n_prev = precisao_revocacao(ev_real, ev_prev, tau=h)

        pd.DataFrame({"real": real, "previsto": prev, "pico_real": pico_real,
                      "pico_previsto": pico_prev}).to_csv(
            f"resultados/picos_{modelo}_{perfil}_h{h}.csv", index=False)
        linhas.append({
            "modelo": modelo.upper(), "perfil": perfil.upper(), "horizonte_min": h * 15 / 60,
            "MAE_nucleos": round(mae, 4), "RMSE_nucleos": round(rmse, 4),
            "MAE_persistencia": round(mae_persist, 4), "ganho_vs_persist_pct": round(ganho, 1),
            "atraso_passos": k, "atraso_frac_horizonte": round(k / h, 2),
            "spikes_precision": round(prec, 3), "spikes_recall": round(rev, 3),
            "picos_reais": n_real, "picos_previstos": n_prev,
            "definicao_pico": f"{args.pico}/{args.eventos}",
        })

    tab = pd.DataFrame(linhas).sort_values(["perfil", "horizonte_min", "modelo"])
    tab.to_csv("resultados/oe2_metricas.csv", index=False)
    pd.set_option("display.width", 200)
    print(tab.drop(columns=["definicao_pico"]).to_string(index=False))
    print("\nganho_vs_persist_pct > 0: o modelo erra menos que repetir o último valor.")
    print("atraso_frac_horizonte ~ 1: o modelo se comporta como persistência; ~ 0: antecipa.")
    print("Salvo em resultados/oe2_metricas.csv (tabela da Seção 4.2)")


if __name__ == "__main__":
    main()