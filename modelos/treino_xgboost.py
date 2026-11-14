"""
Treino do XGBoost (Fase 3 do protocolo)

Hiperparâmetros fixados pelo levantamento bibliográfico (Seção 3.5.3 do TCC):
  200 estimadores (early stopping 20), max_depth=6, learning_rate=0.1,
  subsample=0.8, colsample_bytree=0.8, regularização nos padrões.

Como funciona (a diferença conceitual pra LSTM):
  Árvores não leem sequência - cada amostra precisa ser um vetor "achatado".
  Então a MESMA informação que a LSTM recebe como janela vira colunas:
    - lags do alvo e das features: valores em t-1, t-2, t-3, t-4
    - estatísticas móveis do alvo: média e desvio em janelas de 3, 6 e 12 passos
  Isso NÃO é dado novo (comparação justa do OE2) - é só outra forma de
  apresentar a mesma história recente ao modelo.

Uso:
    python modelos/treino_xgboost.py --perfil a
    python modelos/treino_xgboost.py --perfil b
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

LAGS = [1, 2, 3, 4]
JANELAS_MOVEIS = [3, 6, 12]
HORIZONTES = [4, 40]  # 1 min e 10 min, em passos de 15s
SEED = 42


def montar_tabela(serie: np.ndarray, colunas: list, h: int) -> pd.DataFrame:
    """Monta a tabela supervisionada: lags + estatísticas móveis -> alvo em t+h."""
    df = pd.DataFrame(serie, columns=colunas)
    feats = pd.DataFrame(index=df.index)
    for c in colunas:
        for lag in LAGS:
            feats[f"{c}_lag{lag}"] = df[c].shift(lag)
    for w in JANELAS_MOVEIS:
        feats[f"alvo_media{w}"] = df[colunas[0]].rolling(w).mean()
        feats[f"alvo_desvio{w}"] = df[colunas[0]].rolling(w).std()
    feats["alvo"] = df[colunas[0]].shift(-h)  # o que queremos prever
    return feats.dropna()


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perfil", required=True, choices=["a", "b"])
    args = ap.parse_args()

    d = np.load(f"dados/preparados_{args.perfil}.npz", allow_pickle=True)
    treino, teste, colunas = d["treino"], d["teste"], list(d["colunas"])
    Path("resultados").mkdir(exist_ok=True)

    for h in HORIZONTES:
        tr = montar_tabela(treino, colunas, h)
        te = montar_tabela(teste, colunas, h)
        Xtr, ytr = tr.drop(columns="alvo"), tr["alvo"]
        Xte, yte = te.drop(columns="alvo"), te["alvo"]

        # validação = fatia FINAL do treino (temporal, igual à LSTM)
        corte = int(len(Xtr) * 0.85)
        modelo = xgb.XGBRegressor(
            n_estimators=200, max_depth=6, learning_rate=0.1,
            subsample=0.8, colsample_bytree=0.8,
            objective="reg:squarederror", random_state=SEED,
            early_stopping_rounds=20,
        )
        modelo.fit(
            Xtr.iloc[:corte], ytr.iloc[:corte],
            eval_set=[(Xtr.iloc[corte:], ytr.iloc[corte:])],
            verbose=False,
        )
        print(f"[XGB h={h}] parou em {modelo.best_iteration + 1} árvores")

        pred = modelo.predict(Xte)
        pd.DataFrame({"real": yte.to_numpy(), "previsto": pred}).to_csv(
            f"resultados/pred_xgb_{args.perfil}_h{h}.csv", index=False
        )
        modelo.save_model(f"resultados/xgb_{args.perfil}_h{h}.json")
        print(f"[XGB h={h}] predições salvas em resultados/pred_xgb_{args.perfil}_h{h}.csv")


if __name__ == "__main__":
    main()
