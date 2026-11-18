"""
Gera as figuras do capítulo de resultados em resultados/figuras/:
correlações do OE1, real x previsto do OE2 e curvas de margem do OE3.

Uso: python modelos/figuras.py
"""
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

OUT = Path("resultados/figuras")
OUT.mkdir(parents=True, exist_ok=True)


def fig_oe1(perfil: str) -> None:
    arq = Path(f"resultados/oe1_correlacao_{perfil}.csv")
    if not arq.exists():
        return
    t = pd.read_csv(arq).set_index("feature")
    t = t[t.index != "frontend_cpu"].dropna(subset=["frontend_cpu@1min"])
    t = t.reindex(t["frontend_cpu@1min"].abs().sort_values(ascending=True).index)
    cores = ["tab:orange" if x == "aplicação" else "tab:blue" for x in t["tipo"]]
    fig, ax = plt.subplots(figsize=(9, max(5, 0.32 * len(t))))
    y = np.arange(len(t))
    ax.barh(y - 0.2, t["frontend_cpu@1min"], 0.4, color=cores, label="alvo em +1 min")
    ax.barh(y + 0.2, t["frontend_cpu@10min"], 0.4, color=cores, alpha=0.45, label="alvo em +10 min")
    ax.set_yticks(y); ax.set_yticklabels(t.index)
    ax.axvline(0, color="k", lw=0.6); ax.axvline(0.3, color="gray", ls="--", lw=0.6); ax.axvline(-0.3, color="gray", ls="--", lw=0.6)
    ax.set_xlabel("correlação com frontend_cpu futuro (treino)")
    ax.set_title(f"OE1 - Perfil {perfil.upper()} (azul: infraestrutura | laranja: aplicação)")
    ax.legend(loc="lower right")
    fig.tight_layout(); fig.savefig(OUT / f"fig_oe1_{perfil}.png", dpi=140); plt.close(fig)


def fig_oe2(perfil: str, h: int) -> None:
    arqs = {m: Path(f"resultados/picos_{m}_{perfil}_h{h}.csv") for m in ["lstm", "xgb"]}
    arqs = {m: a for m, a in arqs.items() if a.exists()}
    if not arqs:
        return
    dados = {m: pd.read_csv(a) for m, a in arqs.items()}
    # as séries terminam no mesmo ponto do teste; alinha pelo fim
    n_max = max(len(d) for d in dados.values())
    fig, ax = plt.subplots(figsize=(13, 4.5))
    ref = max(dados.values(), key=len)
    ax.plot(np.arange(n_max), ref["real"], color="k", lw=1.0, label="real")
    idx = np.flatnonzero(ref["pico_real"])
    ax.scatter(idx, ref["real"].iloc[idx], color="red", s=14, zorder=5, label="pico real (Agulló)")
    for m, d in dados.items():
        ax.plot(np.arange(n_max - len(d), n_max), d["previsto"], lw=0.9, alpha=0.9, label=f"previsto {m.upper()}")
    ax.set_xlabel("passo no conjunto de teste (15 s)"); ax.set_ylabel("CPU frontend (núcleos)")
    ax.set_title(f"OE2 - Perfil {perfil.upper()}, horizonte {h * 15 // 60} min")
    ax.legend(ncol=4, fontsize=9)
    fig.tight_layout(); fig.savefig(OUT / f"fig_oe2_{perfil}_h{h}.png", dpi=140); plt.close(fig)


def fig_oe3(perfil: str, h: int) -> None:
    arq = Path("resultados/oe3_margens.csv")
    if not arq.exists():
        return
    t = pd.read_csv(arq)
    t = t[(t["perfil"] == perfil.upper()) & (t["horizonte_min"] == h * 15 / 60)]
    if t.empty:
        return
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.2))
    for est, g in t.groupby("estrategia"):
        g = g.sort_values("margem_pct")
        a1.plot(g["margem_pct"], g["subprov_taxa"] * 100, marker="o", label=est)
        a2.plot(g["margem_pct"], g["overprov_medio"] * 100, marker="o", label=est)
    a1.set_xlabel("margem (%)"); a1.set_ylabel("passos subprovisionados (%)"); a1.set_title("Disponibilidade")
    a2.set_xlabel("margem (%)"); a2.set_ylabel("folga média sobre o consumo (%)"); a2.set_title("Eficiência (overprovisioning)")
    a1.legend(); a2.legend()
    fig.suptitle(f"OE3 - Perfil {perfil.upper()}, horizonte {h * 15 // 60} min")
    fig.tight_layout(); fig.savefig(OUT / f"fig_oe3_{perfil}_h{h}.png", dpi=140); plt.close(fig)


def main() -> None:
    for p in ["a", "b"]:
        fig_oe1(p)
        for h in [4, 40]:
            fig_oe2(p, h); fig_oe3(p, h)
    print("Figuras em", OUT, "->", sorted(x.name for x in OUT.glob("*.png")))


if __name__ == "__main__":
    main()
