"""
Verificação e recorte da coleta (rodar DEPOIS de cada rodada do Locust)

Por que existe: o coletor roda "solto" - começa antes do Locust e costuma ser
parado horas depois dele terminar - e, numa rodada longa, pode haver quedas
momentâneas (ex.: o port-forward do kubectl cai e volta). Dados de períodos sem
carga ou sem coleta contaminam o dataset: a CPU "despenca" por um defeito do
ambiente, e o modelo aprenderia um padrão que não existe na carga.

O que faz:
 1. Lê o histórico do Locust (dados/locust_<perfil>_stats_history.csv) e acha a
    janela em que HOUVE carga (usuários > 0).
 2. Acha os EPISÓDIOS RUINS dentro dessa janela:
      - carga: a maioria das requisições falhou (ou nenhuma completou);
      - coleta: o coletor não gravou nada / gravou NaN.
    Cada episódio é listado (início, fim, duração) e recebe 1 min de margem
    (a CPU usa rate de 1 min, então o efeito "vaza" um pouco).
 3. Retira os episódios e fica com o MAIOR TRECHO CONTÍNUO limpo (a série segue
    sem buracos, o que o split temporal e as janelas da LSTM exigem).
 4. Confere o trecho: falhas residuais, estatística da CPU do frontend e a
    CORRELAÇÃO usuários x CPU (prova de que o consumo responde à carga).
 5. Gera resultados/verificacao_perfil_<p>.png e grava
    dados/metricas_perfil_<p>_recortado.csv - ESTE vai para o preparacao.py.
    O CSV bruto NUNCA é alterado (reprodutibilidade).

Uso:
    python coleta/verificar_coleta.py --perfil a
    python coleta/verificar_coleta.py --perfil b
"""
import argparse
from pathlib import Path

import matplotlib
matplotlib.use("Agg")  # só grava arquivo, não abre janela
import matplotlib.pyplot as plt
import numpy as np
import pandas as pd

ALVO = "frontend_cpu"
LIMIAR_FALHA = 0.5       # passo de 15s é "ruim" se > 50% das requisições falharam
FUNDE_S = 60             # episódios separados por <= 60 s viram um só
MARGEM_S = 60            # margem removida em volta de cada episódio
MIN_LINHAS = {"a": 1000, "b": 900}   # abaixo disso o dataset é curto p/ a LSTM
FUSO_LOCAL = "America/Recife"


def carregar_locust(prefixo: str) -> pd.DataFrame:
    arq = Path(f"{prefixo}_stats_history.csv")
    if not arq.exists():
        raise SystemExit(f"Não achei {arq}. O Locust rodou com --csv {prefixo} ?")
    df = pd.read_csv(arq)
    df = df[df["Name"] == "Aggregated"].copy()
    df["t"] = pd.to_datetime(df["Timestamp"], unit="s", utc=True)
    return df.set_index("t").sort_index()


def episodios(flag: pd.Series) -> list:
    """Sequências consecutivas de True -> [[inicio, fim], ...], fundindo as próximas."""
    brutos, atual = [], None
    for t, f in flag.items():
        if f:
            atual = [t, t] if atual is None else [atual[0], t]
        elif atual is not None:
            brutos.append(atual)
            atual = None
    if atual is not None:
        brutos.append(atual)
    fundidos = []
    for e in brutos:
        if fundidos and (e[0] - fundidos[-1][1]) <= pd.Timedelta(seconds=FUNDE_S + 15):
            fundidos[-1][1] = e[1]
        else:
            fundidos.append(list(e))
    return fundidos


def local(t: pd.Timestamp) -> str:
    try:
        return t.tz_convert(FUSO_LOCAL).strftime("%d/%m %H:%M")
    except Exception:
        return t.strftime("%d/%m %H:%M") + " UTC"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--perfil", required=True, choices=["a", "b"])
    p = ap.parse_args().perfil

    bruto = Path(f"dados/metricas_perfil_{p}.csv")
    if not bruto.exists():
        raise SystemExit(f"Não achei {bruto}.")
    m = pd.read_csv(bruto, parse_dates=["timestamp"]).set_index("timestamp").sort_index()
    m.index = pd.to_datetime(m.index, utc=True)
    loc = carregar_locust(f"dados/locust_perfil_{p}")

    print(f"\n=== Perfil {p.upper()} ===")
    print(f"CSV bruto: {len(m)} linhas = {len(m) * 15 / 3600:.1f} h  "
          f"({local(m.index[0])} -> {local(m.index[-1])} hora local)")

    # ---------- janela com carga ----------
    ativo = loc[loc["User Count"] > 0]
    if ativo.empty:
        raise SystemExit("Locust sem nenhum instante com usuários > 0 - a carga nunca rodou?")
    inicio, fim = ativo.index[0], ativo.index[-1]
    print(f"Carga do Locust: {local(inicio)} -> {local(fim)} hora local "
          f"({(fim - inicio).total_seconds() / 3600:.2f} h, pico de {int(ativo['User Count'].max())} usuários)")

    # ---------- passos de 15s: falhas de carga e buracos de coleta ----------
    tot = loc[["Total Request Count", "Total Failure Count"]].resample("15s").last().ffill()
    d = tot.diff()
    req_s, fal_s = d["Total Request Count"], d["Total Failure Count"]
    usr = loc["User Count"].resample("15s").mean()
    taxa = fal_s / req_s.where(req_s > 0)
    ruim_carga = ((taxa > LIMIAR_FALHA) | ((req_s == 0) & (usr > 0))).loc[inicio:fim]

    grade_m = m[ALVO].resample("15s").mean()
    na = grade_m.isna()
    # Buracos de coleta de até 1 min (4 passos) NÃO cortam a série: o
    # preparacao.py os interpola. Só buracos maiores viram episódio.
    grupo = (na != na.shift()).cumsum()
    tamanho = na.groupby(grupo).transform("size")
    falta_coleta = (na & (tamanho > 4)).reindex(ruim_carga.index, fill_value=False)
    micro = int((na & (tamanho <= 4)).sum())
    if micro:
        print(f"Micro-buracos de coleta tolerados (interpolados na preparação): {micro} passo(s) de 15s")

    total_req, total_fal = float(tot["Total Request Count"].iloc[-1]), float(tot["Total Failure Count"].iloc[-1])
    print(f"Requisições: {int(total_req)}  | falhas: {int(total_fal)} "
          f"({100 * total_fal / max(total_req, 1):.2f}%)")

    eps = [(a, b, "carga (requisições falhando)") for a, b in episodios(ruim_carga)]
    eps += [(a, b, "coleta (sem dados do Prometheus)") for a, b in episodios(falta_coleta)]
    eps.sort(key=lambda e: e[0])

    margem = pd.Timedelta(seconds=MARGEM_S)
    passo = pd.Timedelta(seconds=15)
    if eps:
        print(f"\nEpisódios ruins dentro da janela de carga: {len(eps)}")
        for a, b, tipo in eps:
            dur = (b - a + passo).total_seconds() / 60
            print(f"  - {local(a)} -> {local(b + passo)}  ({dur:.1f} min)  {tipo}")
    else:
        print("\nNenhum episódio ruim dentro da janela de carga.")

    # ---------- trechos contínuos limpos ----------
    cortes = sorted((max(a - margem, inicio), min(b + passo + margem, fim)) for a, b, _ in eps)
    trechos, cursor = [], inicio
    for a, b in cortes:
        if a > cursor:
            trechos.append((cursor, a))
        cursor = max(cursor, b)
    if cursor < fim:
        trechos.append((cursor, fim))
    if not trechos:
        raise SystemExit("Nenhum trecho limpo restou - a rodada precisa ser refeita.")
    s0, s1 = max(trechos, key=lambda t: t[1] - t[0])
    if len(trechos) > 1:
        print("Trechos contínuos limpos:")
        for a, b in trechos:
            marca = "  <- escolhido" if (a, b) == (s0, s1) else ""
            print(f"  - {local(a)} -> {local(b)}  ({(b - a).total_seconds() / 3600:.2f} h){marca}")

    rec = m.loc[s0:s1]
    saida = Path(f"dados/metricas_perfil_{p}_recortado.csv")
    rec.to_csv(saida, index_label="timestamp")
    print(f"\nRecorte: {len(rec)} linhas = {len(rec) * 15 / 3600:.2f} h  "
          f"(descartadas {len(m) - len(rec)} das {len(m)}) -> {saida}")
    if len(rec) < MIN_LINHAS[p]:
        print(f"AVISO: menos de ~{MIN_LINHAS[p]} linhas úteis - dataset curto para a LSTM.")

    # ---------- sanidade do trecho escolhido ----------
    mask = (tot.index >= s0) & (tot.index <= s1)
    r, f = float(req_s[mask].sum()), float(fal_s[mask].sum())
    print(f"Falhas dentro do recorte: {int(f)} de {int(r)} requisições ({100 * f / max(r, 1):.2f}%)")
    cpu_cols = [c for c in rec.columns if c.endswith("_cpu")]
    print(f"Linhas com TODOS os serviços em zero (falha do coletor): {int((rec[cpu_cols].sum(axis=1) == 0).sum())}")
    c = rec[ALVO]
    print(f"{ALVO} (núcleos): min {c.min():.3f} | mediana {c.median():.3f} | "
          f"max {c.max():.3f} | desvio {c.std():.3f}")
    mem = rec["frontend_mem"] / 2**20
    print(f"frontend_mem (MiB): min {mem.min():.0f} | mediana {mem.median():.0f} | max {mem.max():.0f}")

    usuarios = usr.ffill().reindex(rec.index, method="nearest")
    ok = c.notna() & usuarios.notna()
    corr = float(np.corrcoef(usuarios[ok].to_numpy(), c[ok].to_numpy())[0, 1])
    leitura = ("OK - o consumo acompanha a carga" if corr >= 0.5 else
               "FRACA - confira se a carga está chegando ao frontend" if corr >= 0.3 else
               "PROBLEMA - CPU quase não responde à carga")
    print(f"Correlação usuários x {ALVO}: {corr:.2f}  -> {leitura}")

    # ---------- gráfico ----------
    Path("resultados").mkdir(exist_ok=True)
    fig, (a1, a2) = plt.subplots(2, 1, figsize=(13, 7), sharex=True,
                                 gridspec_kw={"height_ratios": [3, 1]})
    a1.plot(m.index, m[ALVO], color="tab:red", lw=0.8)
    a1.set_ylabel("CPU frontend (núcleos)")
    a1b = a1.twinx()
    a1b.step(loc.index, loc["User Count"], color="tab:blue", lw=0.8, where="post")
    a1b.set_ylabel("Usuários (Locust)", color="tab:blue")
    a1.axvspan(m.index[0], s0, color="gray", alpha=0.25)
    a1.axvspan(s1, m.index[-1], color="gray", alpha=0.25)
    for a, b, _ in eps:
        a1.axvspan(a, b + passo, color="red", alpha=0.25)
    a1.set_title(f"Perfil {p.upper()} - verde: trecho usado | cinza: fora do trecho | vermelho: episódio ruim")
    a1.axvspan(s0, s1, color="green", alpha=0.04)
    a2.plot(taxa.index, (taxa.fillna(0) * 100).rolling(4, min_periods=1).mean(), color="tab:orange", lw=0.8)
    a2.set_ylabel("% falhas")
    a2.set_ylim(0, 100)
    fig.tight_layout()
    png = f"resultados/verificacao_perfil_{p}.png"
    fig.savefig(png, dpi=130)
    print(f"Gráfico: {png}\n")


if __name__ == "__main__":
    main()