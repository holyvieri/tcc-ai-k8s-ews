import pandas as pd
import matplotlib.pyplot as plt


def plotar_naive_forecast(caminho_csv, inicio=0, tamanho_fatia=500):
    df = pd.read_csv(caminho_csv)

    df_fatia = df.iloc[inicio: inicio + tamanho_fatia].reset_index(drop=True)

    plt.figure(figsize=(12, 5))
    plt.plot(df_fatia["real"], label="Real (Alvo)", color="#1f77b4", linewidth=2)
    plt.plot(df_fatia["previsto"], label="Previsto", color="#ff7f0e", linestyle="--", linewidth=2)

    plt.title(f"Visualização Real vs Previsto: {caminho_csv}\nObserve o deslocamento horizontal (atraso)")
    plt.xlabel("Passos no Tempo (15s)")
    plt.ylabel("Uso de CPU")
    plt.legend()
    plt.grid(True, alpha=0.3)
    plt.tight_layout()
    plt.show()


if __name__ == "__main__":
    # inspeção visual do atraso da predição (XGBoost, 10 min)
    plotar_naive_forecast("resultados/pred_xgb_a_h40.csv", inicio=0, tamanho_fatia=500)