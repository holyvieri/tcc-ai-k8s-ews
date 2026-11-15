"""
Validação do instrumento de coleta (rodar ANTES de qualquer rodada longa)

Prova, contra uma referência independente, que as consultas do coletor medem
o que dizem medir - em ~1 minuto, não depois de 6 horas.

A referência: o cAdvisor expõe, para cada pod, a série do cgroup do POD
(container="") que É a soma real dos containers. Então, para cada serviço:
    A = consulta do coletor (containers de aplicação)
    P = série do cgroup do pod
  * Coletor correto:  A ~= P (pausa é desprezível)   -> razão A/P ~= 1
  * Bug de dupla contagem (somar tudo): A ~= 2P      -> razão ~= 2  -> REPROVA

Checagens físicas adicionais (um número impossível = instrumento errado):
  * memória de cada serviço DENTRO do limite do manifesto e > 0
  * CPU >= 0 e abaixo do teto configurado

Uso (port-forward do Prometheus ativo):
    python coleta/validar_instrumento.py
Sai com código 0 (APROVADO) ou 1 (REPROVADO) - dá para encadear:
    python coleta/validar_instrumento.py; if ($?) { python coleta/coletor.py ... }
"""
import sys

from prometheus_api_client import PrometheusConnect

from coletor import Q_CPU, Q_MEM, SERVICOS, consultar

LIMITES_MEM_MI = {
    "adservice": 300, "cartservice": 128, "checkoutservice": 128,
    "currencyservice": 128, "emailservice": 128, "frontend": 128,
    "paymentservice": 128, "productcatalogservice": 128,
    "recommendationservice": 450, "shippingservice": 128, "redis-cart": 256,
}
Q_MEM_POD = ('sum(container_memory_working_set_bytes{{namespace="default", '
             'pod=~"{svc}.*", container=""}})')
TOLERANCIA = 0.25   # |A/P - 1| aceitável (pausa + jitter de scrape)


def main() -> None:
    prom = PrometheusConnect(url="http://localhost:9090", disable_ssl=True)
    problemas = []
    print(f"\n{'servico':<24}{'mem app MiB':>12}{'mem pod MiB':>12}{'razao':>7}{'lim MiB':>9}  veredito")
    for svc in SERVICOS:
        app = consultar(prom, Q_MEM.format(svc=svc)) / 2**20
        pod = consultar(prom, Q_MEM_POD.format(svc=svc)) / 2**20
        lim = LIMITES_MEM_MI.get(svc)
        itens = []
        if app <= 0:
            itens.append("memoria zero (consulta vazia?)")
        if pod > 0:
            razao = app / pod
            if abs(razao - 1) > TOLERANCIA:
                itens.append(f"razao app/pod = {razao:.2f} (esperado ~1; ~2 = dupla contagem)")
        else:
            razao = float("nan")
            itens.append("serie do pod ausente - validacao cruzada impossivel")
        if lim and app >= lim:
            itens.append(f"memoria acima do limite ({app:.0f} >= {lim} MiB) - fisicamente impossivel")
        cpu = consultar(prom, Q_CPU.format(svc=svc))
        if cpu < 0 or cpu > 2.5:
            itens.append(f"cpu fora da faixa plausivel: {cpu:.2f}")
        veredito = "ok" if not itens else "; ".join(itens)
        print(f"{svc:<24}{app:>12.0f}{pod:>12.0f}{razao:>7.2f}{(lim or 0):>9}  {veredito}")
        problemas += [f"{svc}: {i}" for i in itens]

    print()
    if problemas:
        print("REPROVADO - não inicie a coleta:")
        for p in problemas:
            print(f"  - {p}")
        sys.exit(1)
    print("APROVADO - instrumento consistente; pode iniciar a coleta.")
    sys.exit(0)


if __name__ == "__main__":
    main()
