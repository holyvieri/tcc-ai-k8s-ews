"""
Coletor de métricas (Fase 1 do protocolo): Prometheus -> CSV

A cada INTERVALO_S segundos, consulta o Prometheus e grava uma linha no CSV
com CPU e memória de cada microsserviço da Online Boutique. Esse CSV É o
dataset bruto da pesquisa.

Pré-requisito (noutro terminal, deixar aberto):
    kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n monitoring 9090:9090

Como rodar (deixar rodando junto com o Locust, por horas):
    conda activate tcc-ews
    python coleta/coletor.py --saida dados/metricas_perfil_a.csv

Use um arquivo de saída POR PERFIL (troque o nome ao trocar o perfil do Locust),
senão os dois perfis se misturam num CSV só.
"""
import argparse
import csv
import time
from datetime import datetime, timezone
from pathlib import Path

from prometheus_api_client import PrometheusConnect

INTERVALO_S = 15  # mesmo intervalo que fecha o lookback da LSTM (20 passos = 5 min)

# Serviços da Online Boutique que entram no vetor multivariado
SERVICOS = [
    "frontend", "cartservice", "productcatalogservice", "currencyservice",
    "paymentservice", "shippingservice", "emailservice", "checkoutservice",
    "recommendationservice", "adservice", "redis-cart",
]

# PromQL: CPU como taxa de uso em núcleos (janela de 1 min) e memória working set
# (working set é o que o kubelet usa pra decidir OOM Kill - por isso essa métrica
#  e não a RSS: é exatamente o número que interessa pro OE3).
Q_CPU = 'sum(rate(container_cpu_usage_seconds_total{{namespace="default", pod=~"{svc}.*"}}[1m]))'
Q_MEM = 'sum(container_memory_working_set_bytes{{namespace="default", pod=~"{svc}.*"}})'


def consultar(prom: PrometheusConnect, query: str) -> float:
    """Executa uma query instantânea e devolve o valor (ou 0.0 se vazio)."""
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
            except Exception as erro:  # ex.: port-forward do Prometheus caiu
                # Não derruba a coleta de horas: grava a linha com NaN (o
                # verificar_coleta.py trata o buraco) e tenta de novo no próximo ciclo.
                print(f"[{datetime.now():%H:%M:%S}] consulta falhou ({type(erro).__name__}); linha NaN")
                linha = [carimbo] + [float("nan")] * (2 * len(SERVICOS))
            w.writerow(linha)
            f.flush()  # grava já: se o PC desligar, o coletado até aqui sobrevive
            # dorme o que falta para completar exatamente INTERVALO_S
            time.sleep(max(0, INTERVALO_S - (time.time() - inicio)))


if __name__ == "__main__":
    main()