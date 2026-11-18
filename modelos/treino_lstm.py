"""
Treina uma LSTM por horizonte (1 e 10 min) para prever a CPU do frontend.

Entrada: janelas com os últimos 20 passos (5 min) de todas as features.
Hiperparâmetros da revisão bibliográfica: 64 -> 32 unidades, dropout 0.2,
Adam 1e-3, batch 32, até 100 épocas com early stopping (paciência 10).
As predições no teste vão para resultados/pred_lstm_<perfil>_h<H>.csv.

Uso: python modelos/treino_lstm.py --perfil a
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models, callbacks

LOOKBACK = 20            # 5 min
HORIZONTES = [4, 40]     # 1 min e 10 min
SEED = 42
tf.keras.utils.set_random_seed(SEED)


def montar_janelas(serie: np.ndarray, h: int):
    # X: (amostras, LOOKBACK, n_features); y: coluna 0, h passos após o fim da janela
    X, y = [], []
    for i in range(LOOKBACK, len(serie) - h + 1):
        X.append(serie[i - LOOKBACK:i, :])
        y.append(serie[i - 1 + h, 0])
    return np.array(X), np.array(y)


def construir_modelo(n_features: int) -> models.Model:
    m = models.Sequential([
        layers.Input(shape=(LOOKBACK, n_features)),
        layers.LSTM(64, return_sequences=True),
        layers.Dropout(0.2),
        layers.LSTM(32),
        layers.Dropout(0.2),
        layers.Dense(1),
    ])
    m.compile(optimizer=tf.keras.optimizers.Adam(learning_rate=1e-3), loss="mse")
    return m


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perfil", required=True, choices=["a", "b"])
    args = ap.parse_args()

    d = np.load(f"dados/preparados_{args.perfil}.npz", allow_pickle=True)
    treino, teste = d["treino"], d["teste"]
    Path("resultados").mkdir(exist_ok=True)

    for h in HORIZONTES:
        Xtr, ytr = montar_janelas(treino, h)
        Xte, yte = montar_janelas(teste, h)
        print(f"[LSTM h={h}] treino {Xtr.shape}, teste {Xte.shape}")

        modelo = construir_modelo(Xtr.shape[2])
        modelo.fit(
            Xtr, ytr,
            validation_split=0.15,          # últimos 15% do treino
            epochs=100, batch_size=32,
            callbacks=[callbacks.EarlyStopping(patience=10, restore_best_weights=True)],
            verbose=2,
        )

        pred = modelo.predict(Xte, verbose=0).ravel()
        pd.DataFrame({"real": yte, "previsto": pred}).to_csv(
            f"resultados/pred_lstm_{args.perfil}_h{h}.csv", index=False
        )
        modelo.save(f"resultados/lstm_{args.perfil}_h{h}.keras")
        print(f"[LSTM h={h}] predições salvas em resultados/pred_lstm_{args.perfil}_h{h}.csv")


if __name__ == "__main__":
    main()
