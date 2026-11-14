"""
Avaliação dos modelos (OE2 / Fase 4 do protocolo)

Lê todas as predições salvas em resultados/pred_*.csv e calcula, para cada
(modelo, perfil, horizonte):
  - MAE  : erro absoluto médio (na escala normalizada 0-1)
  - RMSE : raiz do erro quadrático médio (pesa mais os erros grandes -
           importante aqui, porque errar feio no pico é o pior cenário)
  - Precisão e revocação de PICOS:
      pico = valor REAL acima do percentil 95 da série de teste.
      O modelo "acertou o pico" se o valor PREVISTO também passou do limiar.
      Precisão = dos alarmes que o modelo deu, quantos eram picos de verdade.
      Revocação = dos picos que existiram, quantos o modelo anunciou.
      (Para um EWS, revocação baixa = pico perdido = o pior erro possível.)

Gera resultados/oe2_metricas.csv - essa tabela é, na prática, a Tabela
principal da Seção 4.2 do TCC.

Uso:
    python modelos/avaliacao.py
"""
from pathlib import Path

import numpy as np
import pandas as pd

PERCENTIL_PICO = 95


def metricas(arq: Path) -> dict:
    df = pd.read_csv(arq)
    real, prev = df["real"].to_numpy(), df["previsto"].to_numpy()

    mae = float(np.mean(np.abs(real - prev)))
    rmse = float(np.sqrt(np.mean((real - prev) ** 2)))

    limiar = np.percentile(real, PERCENTIL_PICO)
    pico_real = real >= limiar
    pico_prev = prev >= limiar
    vp = int(np.sum(pico_real & pico_prev))    # verdadeiros positivos
    fp = int(np.sum(~pico_real & pico_prev))   # alarmes falsos
    fn = int(np.sum(pico_real & ~pico_prev))   # picos perdidos
    precisao = vp / (vp + fp) if (vp + fp) else 0.0
    revocacao = vp / (vp + fn) if (vp + fn) else 0.0

    # nome do arquivo carrega os metadados: pred_<modelo>_<perfil>_h<H>.csv
    _, modelo, perfil, hor = arq.stem.split("_")
    return {
        "modelo": modelo.upper(), "perfil": perfil.upper(),
        "horizonte_min": int(hor[1:]) * 15 / 60,
        "MAE": round(mae, 4), "RMSE": round(rmse, 4),
        "precisao_picos": round(precisao, 3), "revocacao_picos": round(revocacao, 3),
        "picos_no_teste": int(np.sum(pico_real)),
    }


def main() -> None:
    arquivos = sorted(Path("resultados").glob("pred_*.csv"))
    if not arquivos:
        print("Nenhum resultados/pred_*.csv encontrado - rode os treinos antes.")
        return
    tabela = pd.DataFrame([metricas(a) for a in arquivos])
    tabela = tabela.sort_values(["perfil", "horizonte_min", "modelo"])
    tabela.to_csv("resultados/oe2_metricas.csv", index=False)
    print(tabela.to_string(index=False))
    print("\nSalvo em resultados/oe2_metricas.csv (tabela da Seção 4.2)")


if __name__ == "__main__":
    main()
