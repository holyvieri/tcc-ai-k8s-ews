"""
Treina um XGBoost por horizonte (1 e 10 min) para prever a CPU do frontend.

Como árvores não leem sequência, a janela recente vira colunas: lags 0 a 4 de
todas as features e média/desvio móveis do alvo (3, 6 e 12 passos).
Hiperparâmetros da revisão bibliográfica: 200 árvores (early stopping 20),
max_depth 6, learning_rate 0.1, subsample e colsample 0.8.

Uso: python modelos/treino_xgboost.py --perfil a
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import xgboost as xgb

LAGS = [0, 1, 2, 3, 4]
JANELAS_MOVEIS = [3, 6, 12]
HORIZONTES = [4, 40]  # 1 min e 10 min
SEED = 42
np.random.seed(SEED)


def montar_tabela(serie: np.ndarray, colunas: list, h: int) -> pd.DataFrame:
    df = pd.DataFrame(serie, columns=colunas)
    feats = pd.DataFrame(index=df.index)
    for c in colunas:
        for lag in LAGS:
            feats[f"{c}_lag{lag}"] = df[c].shift(lag)
    for w in JANELAS_MOVEIS:
        feats[f"alvo_media{w}"] = df[colunas[0]].rolling(w).mean()
        feats[f"alvo_desvio{w}"] = df[colunas[0]].rolling(w).std()
    feats["alvo"] = df[colunas[0]].shift(-h)
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

        # validação: últimos 15% do treino, como na LSTM
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
