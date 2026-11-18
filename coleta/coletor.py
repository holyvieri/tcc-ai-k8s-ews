"""
Coleta CPU e memória de cada serviço da Online Boutique no Prometheus, a cada
15 s, e grava em CSV (dataset bruto).

Requer o port-forward do Prometheus em localhost:9090.
Uso: python coleta/coletor.py --saida dados/metricas_perfil_a.csv
"""
import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

from prometheus_api_client import PrometheusConnect

INTERVALO_S = 15  # 20 passos de 15 s = lookback de 5 min da LSTM

SERVICOS = [
    "frontend", "cartservice", "productcatalogservice", "currencyservice",
    "paymentservice", "shippingservice", "emailservice", "checkoutservice",
    "recommendationservice", "adservice", "redis-cart",
]

# CPU em núcleos (rate de 1 min) e memória working set, que é a usada pelo
# kubelet para OOM Kill. O filtro de container exclui a série agregada do pod
# (container="") e o container de pausa, que dobrariam a soma.
_FILTRO = 'namespace="default", pod=~"{svc}.*", container!="", container!="POD"'
Q_CPU = 'sum(rate(container_cpu_usage_seconds_total{{' + _FILTRO + '}}[1m]))'
Q_MEM = 'sum(container_memory_working_set_bytes{{' + _FILTRO + '}})'


def consultar(prom: PrometheusConnect, query: str) -> float:
    r = prom.custom_query(query=query)
    if not r:
        return 0.0
    return float(r[0]["value"][1])


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--saida", required=True, help="caminho do CSV de saída")
    ap.add_argument("--prometheus", default="http://localhost:9090")
    args = ap.parse_args()

    prom = PrometheusConnect(url=args.prometheus, disable_ssl=True)
    saida = Path(args.saida)
    saida.parent.mkdir(parents=True, exist_ok=True)

    colunas = ["timestamp"] + [f"{s}_cpu" for s in SERVICOS] + [f"{s}_mem" for s in SERVICOS]
    arquivo_novo = not saida.exists()

    print(f"Coletando a cada {INTERVALO_S}s -> {saida}  (Ctrl+C para parar)")
    with saida.open("a", newline="") as f:
        w = csv.writer(f)
        if arquivo_novo:
            w.writerow(colunas)
        while True:
            inicio = time.time()
            carimbo = datetime.now(timezone.utc).isoformat()
            try:
                linha = [carimbo]
                for s in SERVICOS:
                    linha.append(consultar(prom, Q_CPU.format(svc=s)))
                for s in SERVICOS:
                    linha.append(consultar(prom, Q_MEM.format(svc=s)))
            except Exception as erro:
                # falha pontual (ex.: port-forward caiu): grava NaN e segue
                print(f"[{datetime.now():%H:%M:%S}] consulta falhou ({type(erro).__name__}); linha NaN")
                linha = [carimbo] + [float("nan")] * (2 * len(SERVICOS))
            w.writerow(linha)
            f.flush()
            time.sleep(max(0, INTERVALO_S - (time.time() - inicio)))


if __name__ == "__main__":
    main()
