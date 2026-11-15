"""
Checagem de saturação: o consumo medido está "batendo no teto"?

Por que existe: a Online Boutique traz limites de CPU baixos por serviço (ex.:
frontend = 200m = 0,2 núcleo). Quando um serviço encosta no limite, o kernel o
"estrangula" (throttling): a CPU medida fica ACHATADA no teto e deixa de refletir
a demanda real - o pico some da série e o modelo aprenderia um sinal censurado.
Este script mostra, por serviço, o quanto do tempo o consumo ficou perto do limite.

Leitura:
    SATURADO : >= 10% do tempo em >= 90% do limite  -> sinal censurado, não usar
    ATENCAO  : >=  2% do tempo em >= 90% do limite
    OK       : abaixo disso

TETO EFETIVO: serviços de runtime single-thread (Node.js: currency, payment;
Python/GIL: email, recommendation) não passam de ~1 núcleo MESMO com limite de 2.
Para eles o teto considerado é min(limite, 1.0) - senão a checagem diria "OK" para
um serviço que já está no máximo que consegue entregar. (Estimativa conservadora.)

Uso:
    # coleta feita com os limites padrão do manifesto:
    python coleta/checar_saturacao.py --csv dados/metricas_perfil_a_recortado.csv
    # calibração do pico (limites elevados a 2 núcleos); --so-pico analisa só as
    # linhas do platô (total de CPU >= 70% do máximo), sem diluir com o repouso:
    python coleta/checar_saturacao.py --csv dados/calibracao_b.csv --limite-global 2 --so-pico

A "CPU total" (soma dos serviços) deve ficar bem abaixo do nº de CPUs do Docker
Desktop (docker info | Select-String CPUs); senão a própria máquina satura.
"""
import argparse

import pandas as pd

# Limites do manifesto oficial da Online Boutique v0.10.7
# (release/kubernetes-manifests.yaml), conferidos no arquivo do clone usado.
LIMITES_PADRAO = {
    "adservice": 0.3, "cartservice": 0.3, "checkoutservice": 0.2,
    "currencyservice": 0.2, "emailservice": 0.2, "frontend": 0.2,
    "paymentservice": 0.2, "productcatalogservice": 0.2,
    "recommendationservice": 0.2, "shippingservice": 0.2, "redis-cart": 0.125,
}
# Limites de MEMÓRIA (MiB) - NÃO foram elevados no setup; sob o pico, memória
# perto do limite = risco de OOM Kill no meio da coleta (pod reinicia e fura a
# série). A checagem de memória usa sempre estes valores, mesmo com --limite-global.
LIMITES_MEM_MI = {
    "adservice": 300, "cartservice": 128, "checkoutservice": 128,
    "currencyservice": 128, "emailservice": 128, "frontend": 128,
    "paymentservice": 128, "productcatalogservice": 128,
    "recommendationservice": 450, "shippingservice": 128, "redis-cart": 256,
}
PERTO = 0.9   # "perto do limite" = >= 90%
# Teto efetivo (núcleos) de serviços single-thread, independente do limite configurado
TETO_EFETIVO = {"currencyservice": 1.0, "paymentservice": 1.0,
                "emailservice": 1.0, "recommendationservice": 1.0}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--csv", required=True)
    ap.add_argument("--limite-global", type=float, default=None,
                    help="usa este limite (núcleos) para TODOS os serviços")
    ap.add_argument("--so-pico", action="store_true",
                    help="analisa só as linhas do platô (CPU total >= 70%% do máximo)")
    args = ap.parse_args()

    df = pd.read_csv(args.csv)
    if args.so_pico:
        tot = df[[c for c in df.columns if c.endswith("_cpu")]].sum(axis=1)
        df = df[tot >= 0.7 * tot.max()]
        print(f"[--so-pico] analisando {len(df)} linhas do platô")
    linhas = []
    for col in [c for c in df.columns if c.endswith("_cpu")]:
        svc = col[:-4]
        lim = args.limite_global if args.limite_global else LIMITES_PADRAO.get(svc)
        x = df[col].dropna()
        if lim is not None:
            lim = min(lim, TETO_EFETIVO.get(svc, lim))
        if lim is None:
            linhas.append((svc, None, x.median(), x.quantile(0.95), x.max(), 0.0, "sem limite"))
            continue
        frac = float((x >= PERTO * lim).mean())
        status = "SATURADO" if frac >= 0.10 else "ATENCAO" if frac >= 0.02 else "OK"
        linhas.append((svc, lim, x.median(), x.quantile(0.95), x.max(), frac, status))

    linhas.sort(key=lambda r: -r[5])
    print(f"\n{'servico':<24}{'limite':>8}{'mediana':>9}{'p95':>8}{'max':>8}{'%>=90%lim':>11}  status")
    for svc, lim, med, p95, mx, frac, st in linhas:
        lim_s = f"{lim:.2f}" if lim else "  -"
        print(f"{svc:<24}{lim_s:>8}{med:>9.3f}{p95:>8.3f}{mx:>8.3f}{100 * frac:>10.1f}%  {st}")

    # ---------- memória: proximidade de OOM ----------
    print(f"\n{'servico':<24}{'lim MiB':>8}{'mediana':>9}{'p95':>8}{'max':>8}{'%>=90%lim':>11}  status")
    for col in [c for c in df.columns if c.endswith("_mem")]:
        svc = col[:-4]
        lim = LIMITES_MEM_MI.get(svc)
        x = (df[col].dropna() / 2**20)
        x = x[x > 0]
        if lim is None or x.empty:
            print(f"{svc:<24}{'-':>8}{x.median() if len(x) else 0:>9.0f}  (sem limite conhecido)")
            continue
        frac = float((x >= 0.9 * lim).mean())
        st = "RISCO OOM" if frac >= 0.02 or x.max() >= 0.97 * lim else "OK"
        print(f"{svc:<24}{lim:>8}{x.median():>9.0f}{x.quantile(0.95):>8.0f}{x.max():>8.0f}{100 * frac:>10.1f}%  {st}")

    total = df[[c for c in df.columns if c.endswith("_cpu")]].sum(axis=1)
    print(f"\nCPU total dos serviços: mediana {total.median():.2f} | p95 {total.quantile(0.95):.2f} "
          f"| max {total.max():.2f} núcleos")
    print("Compare com as CPUs do Docker Desktop: docker info | Select-String CPUs\n")


if __name__ == "__main__":
    main()