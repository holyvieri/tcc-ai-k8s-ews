"""
Mede se a predição sobe antes ou depois da carga real no pico do teste do
Perfil B (OE2). Complementa spikes-precision/recall, que ficam pouco
informativos com um único evento no teste.

Real e previsto são suavizados (mediana móvel de 5 passos) e compara-se o
primeiro cruzamento de 25%, 50% e 75% da amplitude real. Antecedência > 0
significa que a predição subiu antes; a persistência atrasa exatamente h.

Uso: python modelos/antecedencia.py   (depois do avaliacao.py)
"""
from pathlib import Path

import numpy as np
import pandas as pd

NIVEIS = [0.25, 0.50, 0.75]
SUAVIZACAO = 5


def primeiro_cruzamento(serie: np.ndarray, limiar: float):
    idx = np.flatnonzero(serie >= limiar)
    return int(idx[0]) if len(idx) else None


def main() -> None:
    linhas = []
    for arq in sorted(Path("resultados").glob("picos_*_b_h*.csv")):
        _, modelo, _, hor = arq.stem.split("_")
        h = int(hor[1:])
        d = pd.read_csv(arq)
        real = d["real"].rolling(SUAVIZACAO, center=True, min_periods=1).median().to_numpy()
        prev = d["previsto"].rolling(SUAVIZACAO, center=True, min_periods=1).median().to_numpy()
        base, topo = np.percentile(real, 5), np.percentile(real, 95)
        linha = {"modelo": modelo.upper(), "horizonte_min": h * 15 / 60,
                 "persistencia_min": -h * 15 / 60}
        valores = []
        for n in NIVEIS:
            lim = base + n * (topo - base)
            ir, ip = primeiro_cruzamento(real, lim), primeiro_cruzamento(prev, lim)
            if ir is None or ip is None:
                linha[f"antec_{int(n * 100)}pct_min"] = None
                continue
            a = (ir - ip) * 15 / 60
            linha[f"antec_{int(n * 100)}pct_min"] = round(a, 2)
            valores.append(a)
        linha["antec_media_min"] = round(float(np.mean(valores)), 2) if valores else None
        linhas.append(linha)

    if not linhas:
        print("Nenhum resultados/picos_*_b_h*.csv - rode o avaliacao.py antes.")
        return
    tab = pd.DataFrame(linhas).sort_values(["horizonte_min", "modelo"])
    tab.to_csv("resultados/oe2_antecedencia_b.csv", index=False)
    pd.set_option("display.width", 160)
    print(tab.to_string(index=False))
    print("\n> 0: previsão subiu ANTES da carga real; < 0: DEPOIS. "
          "Persistência = -h por construção.")
    print("Salvo em resultados/oe2_antecedencia_b.csv")


if __name__ == "__main__":
    main()
