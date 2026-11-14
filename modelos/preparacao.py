"""
Preparação dos dados (Fase 2 do protocolo + OE1)

O que este script faz, na ordem:
 1. Carrega o CSV bruto do coletor e regulariza a grade de tempo (15s).
 2. SPLIT TEMPORAL 70/30: bloco mais antigo = treino, mais recente = teste.
    Sem embaralhar - embaralhar vazaria futuro para dentro do treino.
 3. OE1 - seleção de features: correlação de cada coluna com o alvo,
    calculada SÓ NO TREINO (calcular no dataset inteiro também é vazamento).
    Salva a matriz em resultados/correlacao.csv (vira tabela/figura do Cap. 4).
 4. Normalização: scaler ajustado SÓ no treino e aplicado no teste.
 5. Salva treino/teste prontos em dados/preparados_<perfil>.npz.

Uso:
    python modelos/preparacao.py --csv dados/metricas_perfil_a.csv --perfil a
    python modelos/preparacao.py --csv dados/metricas_perfil_b.csv --perfil b
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd

ALVO = "frontend_cpu"      # variável prevista; frontend é a porta de entrada do sistema
FRACAO_TREINO = 0.70
LIMIAR_CORRELACAO = 0.30   # mantém features com |corr| >= limiar (além do próprio alvo)
PASSO_S = 15               # intervalo da grade (deve bater com o coletor)


def carregar(csv: str) -> pd.DataFrame:
    df = pd.read_csv(csv, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    # Regulariza a grade: garante um ponto a cada 15s; buracos curtos (coletor
    # travou por segundos) são interpolados, buracos longos ficam como NaN e caem.
    df = df.resample(f"{PASSO_S}s").mean().interpolate(limit=4).dropna()
    return df


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--perfil", required=True, choices=["a", "b"])
    args = ap.parse_args()

    df = carregar(args.csv)
    print(f"Série carregada: {len(df)} pontos ({len(df) * PASSO_S / 3600:.1f}h), {df.shape[1]} colunas")

    # ---------- 2. split temporal ----------
    corte = int(len(df) * FRACAO_TREINO)
    treino, teste = df.iloc[:corte], df.iloc[corte:]
    print(f"Treino: {len(treino)} pontos | Teste: {len(teste)} pontos")

    # ---------- 3. OE1: correlação no treino ----------
    corr = treino.corr()[ALVO].sort_values(key=abs, ascending=False)
    Path("resultados").mkdir(exist_ok=True)
    corr.to_csv("resultados/correlacao.csv")
    features = [c for c in corr.index if abs(corr[c]) >= LIMIAR_CORRELACAO and c != ALVO]
    print(f"OE1 - features selecionadas (|corr| >= {LIMIAR_CORRELACAO}): {features}")
    colunas = [ALVO] + features  # alvo sempre na posição 0

    # ---------- 4. normalização (min-max ajustado SÓ no treino) ----------
    minimo = treino[colunas].min()
    amplitude = (treino[colunas].max() - minimo).replace(0, 1)  # evita divisão por zero
    tr = ((treino[colunas] - minimo) / amplitude).to_numpy()
    te = ((teste[colunas] - minimo) / amplitude).to_numpy()

    # ---------- 5. salvar ----------
    Path("dados").mkdir(exist_ok=True)
    np.savez(
        f"dados/preparados_{args.perfil}.npz",
        treino=tr, teste=te, colunas=np.array(colunas),
        minimo=minimo.to_numpy(), amplitude=amplitude.to_numpy(),
    )
    print(f"Salvo em dados/preparados_{args.perfil}.npz")


if __name__ == "__main__":
    main()
