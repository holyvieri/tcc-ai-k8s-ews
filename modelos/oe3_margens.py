"""
OE3: aplica margens de 0 a 20% sobre a predição (alocado = previsto x (1 + m))
e mede, no teste, a taxa de subprovisionamento (real > alocado) e a folga
média (overprovisioning).

O baseline REATIVO_SIM aloca o valor observado h passos antes, com as mesmas
margens; h faz o papel da latência de provisionamento. Não é o HPA rodando no
cluster.

Saídas: resultados/oe3_margens.csv e resultados/oe3_equilibrio.csv
Uso: python modelos/oe3_margens.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

from avaliacao import janela_comum, ler_predicoes

MARGENS = [0.00, 0.05, 0.10, 0.15, 0.20]
# subprovisionamento aceitável: estrito (1% dos passos) e tolerante (5%)
LIMIARES_EQUILIBRIO = {"estrito_1pct": 0.01, "tolerante_5pct": 0.05}


def indicadores(real: np.ndarray, alocado: np.ndarray) -> dict:
    sub = real > alocado
    deficit = np.where(sub, (real - alocado) / np.maximum(real, 1e-9), 0.0)
    folga = np.where(~sub, (alocado - real) / np.maximum(real, 1e-9), 0.0)
    return {
        "subprov_taxa": float(sub.mean()),
        "subprov_deficit_medio": float(deficit[sub].mean()) if sub.any() else 0.0,
        "overprov_medio": float(folga[~sub].mean()) if (~sub).any() else 0.0,
        # folga absoluta, útil quando o consumo real é próximo de zero
        "overprov_abs_nucleos": float((alocado - real)[~sub].mean()) if (~sub).any() else 0.0,
    }


def main() -> None:
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
        teste_alvo = d["teste"][:, 0] * amp + minimo

        df = ler_predicoes(arq, n_comum[(perfil, hor)])
        real = df["real"].to_numpy() * amp + minimo
        prev = df["previsto"].to_numpy() * amp + minimo
        n = len(real)
        # reativo: valor observado h passos antes de cada alvo
        pos_alvo = np.arange(len(teste_alvo) - n, len(teste_alvo))
        reativo = teste_alvo[pos_alvo - h]

        for m in MARGENS:
            for nome, base in [(modelo.upper(), prev), ("REATIVO_SIM", reativo)]:
                ind = indicadores(real, base * (1 + m))
                linhas.append({"estrategia": nome, "perfil": perfil.upper(),
                               "horizonte_min": h * 15 / 60, "margem_pct": int(m * 100), **ind})

    tab = pd.DataFrame(linhas).drop_duplicates(
        subset=["estrategia", "perfil", "horizonte_min", "margem_pct"])
    tab = tab.sort_values(["perfil", "horizonte_min", "estrategia", "margem_pct"])
    tab.round(4).to_csv("resultados/oe3_margens.csv", index=False)

    # menor margem que atinge cada limiar
    eq = []
    for chave, g in tab.groupby(["estrategia", "perfil", "horizonte_min"]):
        linha = {"estrategia": chave[0], "perfil": chave[1], "horizonte_min": chave[2],
                 "subprov_sem_margem": round(float(g[g["margem_pct"] == 0]["subprov_taxa"].iloc[0]), 4),
                 "subprov_com_20pct": round(float(g[g["margem_pct"] == 20]["subprov_taxa"].iloc[0]), 4)}
        for nome, lim in LIMIARES_EQUILIBRIO.items():
            ok = g[g["subprov_taxa"] <= lim].sort_values("margem_pct")
            if len(ok):
                linha[f"margem_{nome}"] = f"{int(ok['margem_pct'].iloc[0])}%"
                linha[f"overprov_{nome}"] = round(float(ok["overprov_medio"].iloc[0]), 4)
            else:
                linha[f"margem_{nome}"] = "nao atingida ate 20%"
                linha[f"overprov_{nome}"] = None
        eq.append(linha)
    eq = pd.DataFrame(eq)
    eq.to_csv("resultados/oe3_equilibrio.csv", index=False)

    pd.set_option("display.width", 160)
    print(tab.round(3).to_string(index=False))
    print("\n=== Ponto de equilíbrio: menor margem com subprovisionamento <= 1% (estrito) e <= 5% (tolerante) ===")
    print(eq.to_string(index=False))
    print("\nSalvo: resultados/oe3_margens.csv (Quadro 2) e resultados/oe3_equilibrio.csv")


if __name__ == "__main__":
    main()
