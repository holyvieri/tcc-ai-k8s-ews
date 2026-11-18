# Dados e resultados

Todos os horários estão em UTC e todas as séries usam passo de 15 s.

## dados/

| Arquivo | Origem | Descrição |
|---|---|---|
| `metricas_perfil_<p>.csv` | `coletor.py` | série bruta do Prometheus |
| `metricas_perfil_<p>_recortado.csv` | `verificar_coleta.py` | trecho contínuo com carga, sem episódios ruins |
| `locust_perfil_<p>_stats_history.csv` | Locust (`--csv`) | histórico por segundo: usuários, req/s, falhas/s, latências |
| `locust_perfil_<p>_stats.csv`, `_failures.csv`, `_exceptions.csv` | Locust | resumo por endpoint, falhas e exceções |
| `calibracao_b.csv` | `coletor.py` | rodada curta de calibração do pico do Perfil B |
| `unificado_perfil_<p>.csv` | `preparacao.py` | Prometheus + Locust alinhados, antes da normalização |
| `preparados_<p>.npz` | `preparacao.py` | treino e teste normalizados, usados pelos modelos |
| `descartados/` | | rodadas anteriores, não usadas nos resultados |

### Colunas das métricas do Prometheus

- `timestamp`: instante da consulta (ISO 8601, UTC).
- `<serviço>_cpu`: uso de CPU em núcleos (rate de 1 min).
- `<serviço>_mem`: memória working set em bytes.

Serviços: `frontend`, `cartservice`, `productcatalogservice`,
`currencyservice`, `paymentservice`, `shippingservice`, `emailservice`,
`checkoutservice`, `recommendationservice`, `adservice`, `redis-cart`.

### Colunas adicionadas na junção

`req_por_s`, `falhas_por_s`, `latencia_p50_ms`, `latencia_p95_ms`, médias do
Locust em cada intervalo de 15 s.

### Conteúdo de `preparados_<p>.npz`

| Chave | Conteúdo |
|---|---|
| `treino`, `teste` | matrizes (amostras × features) normalizadas; coluna 0 é o alvo |
| `colunas` | nomes das features selecionadas, na ordem das matrizes |
| `minimo`, `amplitude` | parâmetros do min-max, para voltar a núcleos |
| `indice_teste` | timestamps do conjunto de teste |

## resultados/

| Arquivo | Descrição |
|---|---|
| `verificacao_perfil_<p>.png` | conferência visual da coleta e do recorte |
| `oe1_correlacao_<p>.csv` | correlação de cada feature com CPU e memória do frontend em +1 e +10 min |
| `lstm_<p>_h<H>.keras`, `xgb_<p>_h<H>.json` | modelos treinados |
| `pred_<modelo>_<p>_h<H>.csv` | `real` e `previsto` no teste (normalizados) |
| `picos_<modelo>_<p>_h<H>.csv` | real e previsto em núcleos, com marcação de picos |
| `oe2_metricas.csv` | métricas de erro e de picos por modelo, perfil e horizonte |
| `oe2_antecedencia_b.csv` | antecedência na subida do pico do Perfil B, em minutos |
| `oe3_margens.csv` | indicadores de sub e overprovisioning para margens de 0 a 20% |
| `oe3_equilibrio.csv` | menor margem que atinge 1% e 5% de subprovisionamento |
| `oe3_calibracao.csv` | margem calibrada na validação e desempenho no teste |
| `figuras/` | `fig_oe1_<p>.png`, `fig_oe2_<p>_h<H>.png`, `fig_oe3_<p>_h<H>.png` |

Convenções: `<p>` é o perfil (`a` ou `b`), `<modelo>` é `lstm` ou `xgb` e `H`
é o horizonte em passos de 15 s (4 = 1 min, 40 = 10 min).
