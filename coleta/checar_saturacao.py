"""
Verifica se o consumo de CPU de algum serviço ficou encostado no limite
(throttling), o que achataria os picos da série, e se a memória chegou perto
do limite (risco de OOM Kill).

Status de CPU: SATURADO (>= 10% do tempo acima de 90% do limite),
ATENCAO (>= 2%) ou OK.

Uso:
    python coleta/checar_saturacao.py --csv dados/metricas_perfil_a_recortado.csv
    python coleta/checar_saturacao.py --csv dados/calibracao_b.csv --limite-global 2 --so-pico
"""
import argparse

import pandas as pd

# limites de CPU (núcleos) do manifesto da Online Boutique v0.10.7
LIMITES_PADRAO = {
    "adservice": 0.3, "cartservice": 0.3, "checkoutservice": 0.2,
    "currencyservice": 0.2, "emailservice": 0.2, "frontend": 0.2,
    "paymentservice": 0.2, "productcatalogservice": 0.2,
    "recommendationservice": 0.2, "shippingservice": 0.2, "redis-cart": 0.125,
}
# limites de memória (MiB); não foram alterados no setup
LIMITES_MEM_MI = {
    "adservice": 300, "cartservice": 128, "checkoutservice": 128,
    "currencyservice": 128, "emailservice": 128, "frontend": 128,
    "paymentservice": 128, "productcatalogservice": 128,
    "recommendationservice": 450, "shippingservice": 128, "redis-cart": 256,
}
PERTO = 0.9
# serviços Node.js/Python praticamente single-thread não passam de ~1 núcleo
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

    # memória: proximidade do limite (OOM)
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

    # a soma precisa ficar abaixo das CPUs do Docker Desktop
    total = df[[c for c in df.columns if c.endswith("_cpu")]].sum(axis=1)
    print(f"\nCPU total dos serviços: mediana {total.median():.2f} | p95 {total.quantile(0.95):.2f} "
          f"| max {total.max():.2f} núcleos")
    print("Compare com as CPUs do Docker Desktop: docker info | Select-String CPUs\n")


if __name__ == "__main__":
    main()
