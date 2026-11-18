"""
OE3: escolhe a margem na validação (últimos 15% do treino) e mede o resultado
no teste, evitando escolher a margem olhando o próprio teste.

Estratégias comparadas: LSTM, XGB, REATIVO_SIM (valor de h passos antes) e
ESTATICO (alocação fixa). Para cada meta de subprovisionamento (1% e 5%),
busca a menor margem na validação e reporta no teste a taxa de
subprovisionamento, o déficit, a folga e o fator de custo (alocado médio /
consumo médio). Considera request = limit.

Uso: python modelos/calibrar_margens.py   (usa os modelos já salvos)
"""
from pathlib import Path

import numpy as np
import pandas as pd

from avaliacao import janela_comum, ler_predicoes
from treino_xgboost import montar_tabela

GRADE = np.round(np.arange(0.0, 2.001, 0.01), 2)
METAS = {"1pct": 0.01, "5pct": 0.05}
FRACAO_VAL = 0.15
LOOKBACK = 20


def indicadores(real, alocado):
    sub = real > alocado
    folga = (alocado - real)[~sub]
    return {
        "subprov": float(sub.mean()),
        "deficit_medio": float(((real - alocado) / np.maximum(real, 1e-9))[sub].mean()) if sub.any() else 0.0,
        "folga_media_nucleos": float(folga.mean()) if len(folga) else 0.0,
        "fator_custo": float(alocado.mean() / max(real.mean(), 1e-9)),
    }


def menor_margem(real, base, eps):
    for m in GRADE:
        if np.mean(real > base * (1 + m)) <= eps:
            return float(m)
    return None


def val_lstm(treino, h, perfil):
    try:
        import tensorflow as tf
        from treino_lstm import montar_janelas
    except Exception as e:
        print(f"  [LSTM] pulado: {type(e).__name__}")
        return None
    arq = Path(f"resultados/lstm_{perfil}_h{h}.keras")
    if not arq.exists():
        print(f"  [LSTM] modelo {arq} não encontrado - pulado")
        return None
    X, y = montar_janelas(treino, h)
    corte = int(len(X) * (1 - FRACAO_VAL))
    pos = np.arange(LOOKBACK - 1 + h, len(treino))[corte:]
    modelo = tf.keras.models.load_model(arq)
    prev = modelo.predict(X[corte:], verbose=0).ravel()
    return y[corte:], prev, pos


def val_xgb(treino, colunas, h, perfil):
    import xgboost as xgb
    arq = Path(f"resultados/xgb_{perfil}_h{h}.json")
    if not arq.exists():
        print(f"  [XGB] modelo {arq} não encontrado - pulado")
        return None
    tab = montar_tabela(treino, colunas, h)
    X, y = tab.drop(columns="alvo"), tab["alvo"]
    corte = int(len(X) * (1 - FRACAO_VAL))
    modelo = xgb.XGBRegressor()
    modelo.load_model(arq)
    prev = modelo.predict(X.iloc[corte:])
    pos = tab.index.to_numpy()[corte:] + h
    return y.iloc[corte:].to_numpy(), prev, pos


def main() -> None:
    linhas = []
    for perfil in ["a", "b"]:
        d = np.load(f"dados/preparados_{perfil}.npz", allow_pickle=True)
        treino, teste, colunas = d["treino"], d["teste"], list(d["colunas"])
        mn, amp = float(d["minimo"][0]), float(d["amplitude"][0])
        nuc = lambda v: np.asarray(v) * amp + mn
        for h in [4, 40]:
            print(f"Perfil {perfil.upper()}, h = {h * 15 // 60} min")
            # predições na validação
            val = {}
            for nome, fn in [("LSTM", lambda: val_lstm(treino, h, perfil)),
                             ("XGB", lambda: val_xgb(treino, colunas, h, perfil))]:
                r = fn()
                if r is not None:
                    yv, pv, posv = r
                    val[nome] = (nuc(yv), nuc(pv), posv)
            ref = val.get("XGB") or val.get("LSTM")
            if ref is None:
                continue
            real_v_ref, _, pos_ref = ref
            val["REATIVO_SIM"] = (real_v_ref, nuc(treino[pos_ref - h, 0]), pos_ref)

            # aplica a margem calibrada no teste, no trecho comum a todas as estratégias
            serie_t = teste[:, 0]
            preds = sorted(Path("resultados").glob(f"pred_*_{perfil}_h{h}.csv"))
            n = janela_comum(preds)[(perfil, f"h{h}")]
            for nome in list(val) + ["ESTATICO"]:
                if nome in ("LSTM", "XGB"):
                    arq = Path(f"resultados/pred_{nome.lower()}_{perfil}_h{h}.csv")
                    if not arq.exists():
                        continue
                    dt = ler_predicoes(arq, n)
                    real_t, base_t = nuc(dt["real"]), nuc(dt["previsto"])
                else:
                    pos_t = np.arange(len(serie_t) - n, len(serie_t))
                    real_t = nuc(serie_t[pos_t])
                    base_t = nuc(serie_t[pos_t - h])

                for meta, eps in METAS.items():
                    linha = {"perfil": perfil.upper(), "horizonte_min": h * 15 / 60,
                             "estrategia": nome, "meta": meta}
                    if nome == "ESTATICO":
                        rv = val["REATIVO_SIM"][0]
                        c = float(np.quantile(rv, 1 - eps, method="higher"))
                        aloc = np.full_like(real_t, c)
                        linha.update({"margem_calibrada": f"c = {c:.3f} núcleos",
                                      "margem_oraculo_teste": "-"})
                    else:
                        rv, bv, _ = val[nome]
                        m = menor_margem(rv, bv, eps)
                        mo = menor_margem(real_t, base_t, eps)
                        linha["margem_calibrada"] = f"{m:.0%}" if m is not None else ">200%"
                        linha["margem_oraculo_teste"] = f"{mo:.0%}" if mo is not None else ">200%"
                        if m is None:
                            linhas.append(linha)
                            continue
                        aloc = base_t * (1 + m)
                    ind = indicadores(real_t, aloc)
                    ind["atinge_meta_no_teste"] = "sim" if ind["subprov"] <= eps else "não"
                    linha.update({k: (round(v, 4) if isinstance(v, float) else v) for k, v in ind.items()})
                    linhas.append(linha)

    tab = pd.DataFrame(linhas)
    tab.to_csv("resultados/oe3_calibracao.csv", index=False)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_columns", 20)
    print()
    print(tab.to_string(index=False))
    print("\nmargem_calibrada: escolhida na VALIDAÇÃO | indicadores: medidos no TESTE")
    print("fator_custo: alocado médio / consumo real médio (1,0 = sem folga)")
    print("Salvo em resultados/oe3_calibracao.csv")


if __name__ == "__main__":
    main()
