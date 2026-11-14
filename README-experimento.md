# Ambiente Experimental — Autoscaling Preditivo para EWS

Experimento do TCC: predição de consumo de CPU/memória (LSTM vs. XGBoost) com atuação
real via KEDA em cluster Kubernetes local, sob dois perfis de carga (rotina e pico de emergência).

## Reprodutibilidade

- **Ferramentas e libs Python**: versões pinadas em `setup-experimento.ps1` e `requirements.txt`.
- **Charts Helm (Prometheus, KEDA)**: instalados na versão mais recente no momento do setup e
  registrados em `versoes-instaladas.txt` (gerado automaticamente pelo script) — esse arquivo é o
  registro oficial das versões sob as quais os resultados foram obtidos. Commitar após o primeiro setup.

## Setup (Windows / PowerShell)

Pré-requisitos: Docker Desktop instalado e aberto (WSL 2), Anaconda instalado,
[Online Boutique](https://github.com/GoogleCloudPlatform/microservices-demo) clonada.

```powershell
# 1a vez, se o Windows bloquear scripts locais:
Set-ExecutionPolicy -Scope CurrentUser -ExecutionPolicy RemoteSigned

.\setup-experimento.ps1 -BoutiquePath "C:\caminho\para\microservices-demo"
```

O script é idempotente: confere cada etapa antes de executar e pode ser rodado de novo após
qualquer falha intermediária. Ao final, ativar o ambiente Python com `conda activate tcc-ews`.

## Sequência experimental (protocolo)

1. **Fase 1 — Geração e coleta**: Locust aplica os Perfis A (rotina) e B (pico) sobre a
   Online Boutique; coletor lê as métricas do Prometheus e grava a série temporal bruta.
2. **Fase 2 — Split temporal**: bloco mais antigo para treino, mais recente para teste
   (sem embaralhamento, para não vazar futuro no treino).
3. **Fase 3 — Treino**: LSTM e XGBoost, hiperparâmetros fixados por levantamento
   bibliográfico (ver seção 3.5.3 do TCC).
4. **Fase 4 — Avaliação (OE2)**: MAE, RMSE e detecção de picos no conjunto de teste.
5. **OE3 — Margens de segurança**: a predição é publicada como métrica; o ScaledObject do
   KEDA a consome com margens de 10% e 15%; compara-se OOM Kills e overprovisioning
   contra o baseline reativo (HPA nativo).

## Estrutura sugerida do repositório

```
├── setup-experimento.ps1
├── requirements.txt
├── versoes-instaladas.txt        # gerado pelo setup; commitar
├── README-experimento.md
├── locust/                       # perfis A e B
├── coleta/                       # scripts de coleta Prometheus -> CSV
├── notebooks/                    # OE1 (features), treino, OE2
├── keda/                         # ScaledObjects (margens 10% e 15%)
└── dados/                        # séries coletadas (ou .gitignore se pesadas)
```
