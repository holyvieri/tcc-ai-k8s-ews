"""
Treino da LSTM (Fase 3 do protocolo)

Hiperparâmetros fixados pelo levantamento bibliográfico (Seção 3.5.3 do TCC):
  2 camadas (64 -> 32), dropout 0.2, Adam lr=1e-3, batch 32, até 100 épocas
  com early stopping (paciência 10, val_loss), lookback de 20 passos (5 min a 15s).

Como funciona:
  - A série vira pares (janela, alvo): a janela são os últimos 20 passos de
    TODAS as features; o alvo é o valor do frontend_cpu H passos à frente.
  - Treina um modelo POR HORIZONTE (1 min = 4 passos; 10 min = 40 passos).
  - As predições sobre o TESTE são salvas em resultados/pred_lstm_<perfil>_h<H>.csv
    para a avaliação (OE2) e para o OE3.

Uso:
    python modelos/treino_lstm.py --perfil a
    python modelos/treino_lstm.py --perfil b
"""
import argparse
from pathlib import Path

import numpy as np
import pandas as pd
import tensorflow as tf
from tensorflow.keras import layers, models, callbacks

LOOKBACK = 20            # 20 passos x 15s = 5 min de contexto
HORIZONTES = [4, 40]     # em passos: 1 min e 10 min (recorte final do escopo)
SEED = 42                # reprodutibilidade


def montar_janelas(serie: np.ndarray, h: int):
    """Transforma a série (N, n_features) em:
       X: (amostras, LOOKBACK, n_features)  - as janelas de entrada
       y: (amostras,)                        - alvo (coluna 0) h passos à frente
    """
    X, y = [], []
    for i in range(LOOKBACK, len(serie) - h):
        X.append(serie[i - LOOKBACK:i, :])
        y.append(serie[i + h, 0])  # coluna 0 = alvo (frontend_cpu)
    return np.array(X), np.array(y)


def construir_modelo(n_features: int) -> models.Model:
    tf.random.set_seed(SEED)
    m = models.Sequential([
        layers.Input(shape=(LOOKBACK, n_features)),
        layers.LSTM(64, return_sequences=True),   # 1a camada vê a sequência inteira
        layers.Dropout(0.2),
        layers.LSTM(32),                          # 2a camada condensa num vetor
        layers.Dropout(0.2),
        layers.Dense(1),                          # saída: valor previsto (regressão)
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
            validation_split=0.15,          # fatia FINAL do treino p/ early stopping
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
