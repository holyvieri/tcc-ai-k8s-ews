# Autoscaling preditivo para Sistemas de Alerta Precoce (EWS) em Kubernetes

Repositório do Trabalho de Conclusão de Curso (UPE) que investiga se modelos de
predição de séries temporais conseguem antecipar o consumo de recursos de uma
aplicação em microsserviços e, com isso, apoiar um autoscaling preditivo mais
adequado a Sistemas de Alerta Precoce (Early Warning Systems, EWS) do que o
escalonamento puramente reativo.

## Contexto

Um EWS de cheias passa a maior parte do tempo com carga baixa e estável. Quando
um alerta é emitido, a população passa a acessar o sistema ao mesmo tempo, e a
carga sobe muito em pouco tempo (flash crowd). É justamente nesse momento que o
sistema não pode ficar indisponível.

O autoscaling reativo do Kubernetes (HPA) só age depois que o consumo já subiu,
e a nova capacidade ainda leva um tempo para ficar pronta. Se o aumento puder
ser previsto com alguns minutos de antecedência, os recursos podem ser
reservados antes do pico.

Como não há acesso a um EWS real em produção, o experimento usa a
[Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo)
(aplicação de referência com 11 microsserviços) num cluster Kind local e gera
carga com o Locust em dois perfis:

- **Perfil A (rotina):** carga oscilando suavemente em torno de 30 usuários.
- **Perfil B (emergência):** rotina de 30 usuários seguida de subida até 300,
  platô e decaimento, com a proporção entre as fases tirada de um hidrograma
  de cheia do GloFAS. O ciclo se repete três vezes.

## Objetivos específicos

| | Pergunta | Onde está |
|---|---|---|
| **OE1** | Quais métricas (infraestrutura x aplicação) se correlacionam com o consumo futuro de CPU do frontend? | `modelos/preparacao.py`, `resultados/oe1_correlacao_*.csv` |
| **OE2** | LSTM e XGBoost preveem o consumo com 1 e 10 min de antecedência melhor que a persistência? Antecipam os picos? | `modelos/avaliacao.py`, `modelos/antecedencia.py`, `resultados/oe2_*.csv` |
| **OE3** | Que margem de segurança sobre a predição evita subprovisionamento sem desperdiçar recursos, comparada a uma política reativa? | `modelos/oe3_margens.py`, `modelos/calibrar_margens.py`, `resultados/oe3_*.csv` |

O alvo de predição é a CPU do `frontend` (em núcleos), amostrada a cada 15 s.

## Estrutura do repositório

```
├── setup-experimento.ps1      # sobe todo o ambiente (Kind, Boutique, Prometheus, KEDA, conda)
├── requirements.txt           # bibliotecas Python com versões fixadas
├── versoes-instaladas.txt     # versões efetivamente instaladas (gerado pelo setup)
├── Hiperparâmetros - tcc - ews.xlsx   # levantamento dos hiperparâmetros na literatura
├── k8s/
│   └── patch-emailservice.json   # afrouxa as probes do emailservice no Kind
├── locust/
│   ├── perfil_a.py            # carga de rotina
│   └── perfil_b.py            # carga de emergência
├── coleta/
│   ├── validar_instrumento.py # confere as consultas PromQL antes da coleta
│   ├── coletor.py             # Prometheus -> CSV a cada 15 s
│   ├── verificar_coleta.py    # recorta a janela de carga e remove trechos ruins
│   └── checar_saturacao.py    # verifica throttling de CPU e risco de OOM
├── modelos/
│   ├── preparacao.py          # junção, split temporal, OE1, normalização
│   ├── treino_lstm.py
│   ├── treino_xgboost.py
│   ├── avaliacao.py           # métricas do OE2
│   ├── antecedencia.py        # antecedência na subida do pico (Perfil B)
│   ├── oe3_margens.py         # margens fixas de 0 a 20%
│   ├── calibrar_margens.py    # margem calibrada na validação
│   └── figuras.py             # figuras do capítulo de resultados
├── plot_prova.py              # gráfico rápido de real x previsto
├── dados/                     # séries coletadas e dados preparados
└── resultados/                # predições, modelos salvos, tabelas e figuras
```

## Ambiente

- Windows com Docker Desktop (WSL 2) e Anaconda
- Kind v0.25.0 (Kubernetes 1.31), kubectl, Helm
- kube-prometheus-stack via Helm (o KEDA também é instalado, mas não foi usado
  nos resultados; o OE3 é avaliado offline)
- Limite de CPU dos serviços da Boutique elevado para 2 núcleos, para que o
  pico não seja achatado por throttling
- Python 3.10: TensorFlow 2.17, XGBoost 2.1, pandas, scikit-learn, Locust 2.31

As versões exatas usadas para gerar os resultados estão em
`versoes-instaladas.txt`.

## Como reproduzir

### 1. Ambiente

Clonar a Online Boutique e executar o setup (no PowerShell):

```powershell
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned   # só na primeira vez
.\setup-experimento.ps1 -BoutiquePath "C:\caminho\para\microservices-demo"
conda activate tcc-ews
```

O script confere cada etapa antes de executá-la, então pode ser rodado de novo
após uma falha. Ele também desliga o `loadgenerator` da Boutique, para que toda
a carga venha do Locust.

Depois do setup, o limite de CPU dos serviços foi elevado manualmente para 2
núcleos (passo fora do script, feito antes da calibração e das coletas):

```powershell
foreach ($svc in "frontend","cartservice","productcatalogservice","currencyservice","paymentservice","shippingservice","emailservice","checkoutservice","recommendationservice","adservice","redis-cart") {
    kubectl set resources deployment $svc --limits=cpu=2
}
```

### 2. Coleta (um perfil por vez)

Em terminais separados:

```powershell
kubectl port-forward svc/monitoring-kube-prometheus-prometheus -n monitoring 9090:9090
kubectl port-forward svc/frontend 8080:80
```

```powershell
python coleta/validar_instrumento.py
python coleta/coletor.py --saida dados/metricas_perfil_a.csv
locust -f locust/perfil_a.py --host http://localhost:8080 --headless --csv dados/locust_perfil_a
```

Ao terminar a carga, parar o coletor e recortar:

```powershell
python coleta/verificar_coleta.py --perfil a
python coleta/checar_saturacao.py --csv dados/metricas_perfil_a_recortado.csv
```

Repetir com `perfil_b` / `--perfil b`.

### 3. Modelagem e análise

```powershell
python modelos/preparacao.py --perfil a
python modelos/preparacao.py --perfil b
python modelos/treino_lstm.py --perfil a
python modelos/treino_lstm.py --perfil b
python modelos/treino_xgboost.py --perfil a
python modelos/treino_xgboost.py --perfil b
python modelos/avaliacao.py
python modelos/antecedencia.py
python modelos/oe3_margens.py
python modelos/calibrar_margens.py
python modelos/figuras.py
```

Todos os comandos devem ser executados a partir da raiz do repositório.

## Principais saídas

| Arquivo | Conteúdo |
|---|---|
| `resultados/oe1_correlacao_<p>.csv` | correlação de cada feature com o alvo em +1 e +10 min (treino) |
| `resultados/pred_<modelo>_<p>_h<H>.csv` | valores reais e previstos no teste (normalizados) |
| `resultados/oe2_metricas.csv` | MAE, RMSE, ganho sobre a persistência, atraso, spikes-precision/recall |
| `resultados/oe2_antecedencia_b.csv` | antecedência da predição na subida do pico do Perfil B |
| `resultados/oe3_margens.csv` | subprovisionamento e overprovisioning por margem |
| `resultados/oe3_equilibrio.csv` | menor margem que atinge 1% e 5% de subprovisionamento |
| `resultados/oe3_calibracao.csv` | margem escolhida na validação e desempenho no teste |
| `resultados/figuras/` | figuras do capítulo de resultados |

`<p>` é o perfil (`a` ou `b`) e `H` o horizonte em passos de 15 s (4 = 1 min,
40 = 10 min).

## Documentação complementar

- [docs/metodologia.md](docs/metodologia.md): detalhes de cada etapa, decisões
  metodológicas e limitações.
- [docs/dados.md](docs/dados.md): descrição dos arquivos de dados e de resultados.

## Licença

MIT. Ver [LICENSE](LICENSE).
