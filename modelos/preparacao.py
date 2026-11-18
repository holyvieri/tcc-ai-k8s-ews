"""
Junta as métricas do Prometheus (infraestrutura) com as do Locust (aplicação)
numa grade de 15 s, faz o split temporal 70/30, calcula a correlação de cada
feature com o alvo futuro (OE1), seleciona as features e normaliza com
min-max ajustado só no treino.

User Count e as colunas "Total ..." do Locust ficam de fora: a primeira não
existe em produção e as outras são acumuladas.

Uso: python modelos/preparacao.py --perfil a
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ALVO = "frontend_cpu"
ALVOS_OE1 = ["frontend_cpu", "frontend_mem"]
HORIZONTES = {"1min": 4, "10min": 40}         # em passos de 15 s
FRACAO_TREINO = 0.70
LIMIAR_CORRELACAO = 0.30
PASSO = "15s"

# colunas instantâneas do stats_history do Locust
COLS_LOCUST = {"Requests/s": "req_por_s", "Failures/s": "falhas_por_s",
               "50%": "latencia_p50_ms", "95%": "latencia_p95_ms"}


def carregar_prometheus(perfil: str) -> pd.DataFrame:
    arq = Path(f"dados/metricas_perfil_{perfil}_recortado.csv")
    df = pd.read_csv(arq, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    df.index = pd.to_datetime(df.index, utc=True)
    mem = [c for c in df.columns if c.endswith("_mem")]
    n_zero = int((df[mem] == 0).sum().sum())
    df[mem] = df[mem].replace(0, np.nan)   # 0 indica consulta vazia
    if n_zero:
        print(f"  memória = 0 tratada como ausente em {n_zero} valor(es)")
    return df.resample(PASSO, label="right", closed="right").mean()


def carregar_locust(perfil: str) -> pd.DataFrame:
    arq = Path(f"dados/locust_perfil_{perfil}_stats_history.csv")
    df = pd.read_csv(arq)
    df = df[df["Name"] == "Aggregated"].copy()
    df["t"] = pd.to_datetime(df["Timestamp"], unit="s", utc=True)
    df = df.set_index("t").sort_index()[list(COLS_LOCUST)].rename(columns=COLS_LOCUST)
    df = df.apply(pd.to_numeric, errors="coerce")
    # média de cada intervalo de 15 s, rotulada pelo fim (como o coletor)
    return df.resample(PASSO, label="right", closed="right").mean()


def juntar(prom: pd.DataFrame, loc: pd.DataFrame) -> pd.DataFrame:
    ini, fim = max(prom.index[0], loc.index[0]), min(prom.index[-1], loc.index[-1])
    df = prom.loc[ini:fim].join(loc.loc[ini:fim], how="left")
    faltas = df.isna().sum()
    df = df.interpolate(limit=4)            # buracos de até 1 min
    perdidas = int(df.isna().any(axis=1).sum())
    df = df.dropna()
    print(f"  janela comum: {ini:%d/%m %H:%M} -> {fim:%d/%m %H:%M} UTC | {len(df)} linhas")
    if perdidas:
        print(f"  linhas descartadas por buraco longo: {perdidas}")
    piores = faltas[faltas > 0].sort_values(ascending=False).head(3)
    if len(piores):
        print("  colunas com mais ausentes antes da interpolação: " +
              ", ".join(f"{c}={n}" for c, n in piores.items()))
    return df


def relatorio_qualidade(df: pd.DataFrame) -> None:
    print("\n--- Qualidade do dataset unificado ---")
    print(f"  {len(df)} linhas x {df.shape[1]} colunas | {len(df) * 15 / 3600:.2f} h")
    quase_const = [c for c in df.columns if df[c].std() < 1e-9]
    if quase_const:
        print(f"  colunas constantes (serão descartadas na seleção): {quase_const}")
    for c in [ALVO, "req_por_s", "latencia_p95_ms"]:
        if c in df:
            print(f"  {c}: min {df[c].min():.3f} | mediana {df[c].median():.3f} | max {df[c].max():.3f}")
    # se a junção estiver certa, requisições e CPU do frontend andam juntas
    r = df["req_por_s"].corr(df[ALVO])
    aviso = "" if r >= 0.5 else "   <-- BAIXA: confira o alinhamento temporal"
    print(f"  correlação req_por_s x {ALVO} (sanidade da junção): {r:.2f}{aviso}")


def oe1_correlacoes(treino: pd.DataFrame, perfil: str) -> pd.DataFrame:
    # corr(feature em t, alvo em t+h), calculada só no treino
    linhas = {}
    for alvo in ALVOS_OE1:
        for nome, h in HORIZONTES.items():
            futuro = treino[alvo].shift(-h)
            linhas[f"{alvo}@{nome}"] = treino.corrwith(futuro)
    tab = pd.DataFrame(linhas)
    tab.index.name = "feature"
    tab["tipo"] = ["aplicação" if f in COLS_LOCUST.values() else "infraestrutura" for f in tab.index]
    Path("resultados").mkdir(exist_ok=True)
    tab.round(3).to_csv(f"resultados/oe1_correlacao_{perfil}.csv")
    print(f"\n--- OE1 (treino) - corr com o alvo futuro -> resultados/oe1_correlacao_{perfil}.csv")
    col = f"{ALVO}@1min"
    print(tab[[col, f"{ALVO}@10min", "tipo"]].sort_values(col, key=abs, ascending=False)
             .head(12).round(3).to_string())
    return tab


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perfil", required=True, choices=["a", "b"])
    args = ap.parse_args()

    print(f"=== Perfil {args.perfil.upper()} ===")
    df = juntar(carregar_prometheus(args.perfil), carregar_locust(args.perfil))
    relatorio_qualidade(df)

    # split temporal, sem embaralhar
    corte = int(len(df) * FRACAO_TREINO)
    treino, teste = df.iloc[:corte], df.iloc[corte:]
    print(f"\n--- Split temporal: treino {len(treino)} | teste {len(teste)} "
          f"(corte em {treino.index[-1]:%d/%m %H:%M} UTC)")

    tab = oe1_correlacoes(treino, args.perfil)
    # fica a feature com |corr| >= limiar em algum dos horizontes
    score = tab[[f"{ALVO}@{n}" for n in HORIZONTES]].abs().max(axis=1)
    features = [f for f in score.index if score[f] >= LIMIAR_CORRELACAO and f != ALVO
                and not np.isnan(score[f])]
    print(f"\n--- Features selecionadas (|corr| >= {LIMIAR_CORRELACAO} em algum horizonte): "
          f"{len(features)}\n  {features}")
    colunas = [ALVO] + features   # alvo sempre na coluna 0

    # min-max com parâmetros do treino
    minimo = treino[colunas].min()
    amplitude = (treino[colunas].max() - minimo).replace(0, 1)
    tr = ((treino[colunas] - minimo) / amplitude).to_numpy(dtype=np.float32)
    te = ((teste[colunas] - minimo) / amplitude).to_numpy(dtype=np.float32)

    Path("dados").mkdir(exist_ok=True)
    np.savez(f"dados/preparados_{args.perfil}.npz",
             treino=tr, teste=te, colunas=np.array(colunas),
             minimo=minimo.to_numpy(), amplitude=amplitude.to_numpy(),
             indice_teste=teste.index.astype(str).to_numpy())
    df.to_csv(f"dados/unificado_perfil_{args.perfil}.csv", index_label="timestamp")
    print(f"\nSalvo: dados/preparados_{args.perfil}.npz e dados/unificado_perfil_{args.perfil}.csv")


if __name__ == "__main__":
    main()
