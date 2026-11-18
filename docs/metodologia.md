# Metodologia do experimento

Este documento descreve como o experimento foi montado e por que cada decisão
foi tomada. A ordem segue o fluxo dos dados: ambiente, geração de carga,
coleta, preparação, modelos, avaliação (OE2) e margens de segurança (OE3).

## 1. Ambiente

O cluster roda localmente em Kind sobre o Docker Desktop. A aplicação é a
Online Boutique, instalada a partir de `release/kubernetes-manifests.yaml`.
Alguns ajustes feitos no setup:

- O `loadgenerator` da Boutique é escalado para zero réplicas. Ele gera
  tráfego próprio e misturaria sua carga com a dos perfis do Locust.
- O `emailservice` recebe um patch nas probes (`k8s/patch-emailservice.json`).
  No Kind ele demorava a abrir a porta e era reiniciado pela liveness probe. O
  patch não mexe em requests nem em limits.
- Prometheus (kube-prometheus-stack) e KEDA são instalados via Helm. O KEDA
  foi instalado prevendo a atuação do autoscaling no cluster, mas não chegou a
  ser usado nos resultados (ver Limitações).

Os limites de CPU padrão da Boutique são baixos (0,2 núcleo no frontend, por
exemplo). Com eles, o pico do Perfil B ficaria achatado pelo throttling e o
modelo aprenderia um sinal censurado. Por isso, depois do setup, o limite de
CPU de todos os serviços foi elevado manualmente para 2 núcleos
(`kubectl set resources deployment <serviço> --limits=cpu=2`), sem alterar
requests nem limites de memória. Esse passo não faz parte do
`setup-experimento.ps1`; o comando está no README.

A elevação foi feita antes da rodada de calibração (`dados/calibracao_b.csv`),
verificada com `coleta/checar_saturacao.py`, e mantida na coleta do Perfil B.
No Perfil A o consumo fica bem abaixo até dos limites padrão (o frontend passa
de 90% do limite de 0,2 núcleo em apenas 0,1% do tempo), então o resultado não
depende do limite usado nessa rodada.

## 2. Perfis de carga (Locust)

Os dois perfis usam o cliente `FastHttpUser` e o mesmo think time (1 a 10 s),
para que a diferença entre eles venha só da forma da carga.

### Perfil A: rotina

- Comportamento do usuário igual ao locustfile oficial da Boutique: home,
  troca de moeda, navegação em produtos, carrinho e checkout, com os mesmos
  pesos.
- Usuários simultâneos: `30 + 10·sen(2πt / 20 min)` mais um ruído inteiro
  entre -3 e 3.
- O período de 20 min é o dobro do maior horizonte de predição.
- Duração: 340 min.

### Perfil B: emergência

- Comportamento do usuário: consulta repetida da home e de produtos, com pouca
  adição ao carrinho e sem checkout. É uma premissa do trabalho, que representa
  a população consultando o alerta.
- Ciclo: 30 min de rotina (30 usuários), 21 min de subida, 18 min de platô
  (300 usuários) e 42 min de decaimento, repetido 3 vezes.
- A proporção das fases vem da mediana do hidrograma IFS ENS do GloFAS para o
  ponto DM000831 (bacia do Douro), com cerca de 3,5 dias de subida, 3 de pico e
  7 de recessão. A escala usada foi 1 dia = 6 min.
- A razão 10:1 entre pico e rotina vem da literatura de flash crowd. Do GloFAS
  vem apenas a forma temporal; não se assume relação entre vazão do rio e
  número de acessos.

## 3. Coleta

### Instrumento

`coleta/coletor.py` consulta o Prometheus a cada 15 s e grava, para cada um
dos 11 serviços:

- **CPU:** `rate(container_cpu_usage_seconds_total[1m])`, em núcleos;
- **memória:** `container_memory_working_set_bytes`, a métrica usada pelo
  kubelet para decidir OOM Kill.

O cAdvisor expõe, além dos containers da aplicação, uma série agregada do pod
(`container=""`) e a do container de pausa (`container="POD"`). Sem filtrar
essas duas, a soma contaria o consumo em dobro. `coleta/validar_instrumento.py`
compara a soma dos containers com a série do pod antes de cada rodada: a razão
deve ficar perto de 1.

Se uma consulta falha (por exemplo, quando o port-forward cai), a linha é
gravada com NaN e a coleta continua.

### Limpeza

O coletor é iniciado antes do Locust e parado depois dele, então o CSV bruto
tem trechos sem carga. `coleta/verificar_coleta.py`:

1. usa o `stats_history` do Locust para achar a janela com usuários ativos;
2. marca como ruins os passos em que mais de 50% das requisições falharam e os
   buracos de coleta maiores que 1 min;
3. remove esses episódios com 1 min de margem e mantém o maior trecho contínuo;
4. confere a correlação entre usuários e CPU do frontend;
5. grava `dados/metricas_perfil_<p>_recortado.csv` e um gráfico em
   `resultados/verificacao_perfil_<p>.png`.

O CSV bruto não é alterado. Rodadas descartadas foram mantidas em
`dados/descartados/`.

## 4. Preparação e OE1

`modelos/preparacao.py`:

- reamostra Prometheus e Locust na mesma grade de 15 s (UTC), rotulando cada
  intervalo pelo fim;
- do Locust usa apenas as colunas instantâneas: requisições/s, falhas/s e
  latências p50 e p95. `User Count` fica de fora por ser a variável de controle
  da simulação, que não existiria em produção. As colunas `Total ...` também
  ficam de fora por serem acumuladas;
- interpola buracos de até 1 min e descarta o restante;
- separa treino e teste em ordem temporal (70/30), sem embaralhar.

O OE1 calcula, só no treino, a correlação de Pearson entre cada feature em
`t` e o alvo em `t + h`, para h = 1 e 10 min e para CPU e memória do frontend.
São selecionadas as features com |r| ≥ 0,30 em algum dos horizontes (alvo:
CPU). A normalização min-max também é ajustada só no treino.

A única operação feita antes do split é a interpolação dos buracos curtos,
cujo efeito sobre o teste é desprezível.

## 5. Modelos

Os hiperparâmetros foram fixados a partir do levantamento bibliográfico
(planilha `Hiperparâmetros - tcc - ews.xlsx`), sem busca no conjunto de teste.
Um modelo é treinado para cada combinação de perfil e horizonte.

| | LSTM | XGBoost |
|---|---|---|
| Entrada | janela de 20 passos (5 min) com todas as features | lags 0 a 4 de todas as features + média e desvio móveis do alvo (3, 6 e 12 passos) |
| Arquitetura | LSTM(64) → Dropout 0,2 → LSTM(32) → Dropout 0,2 → Dense(1) | 200 árvores, max_depth 6, lr 0,1, subsample 0,8, colsample 0,8 |
| Treino | Adam 1e-3, MSE, batch 32, até 100 épocas | squared error |
| Parada antecipada | paciência 10 sobre os últimos 15% do treino | 20 rodadas sobre os últimos 15% do treino |
| Semente | 42 | 42 |

Nos dois casos o alvo é o valor da CPU do frontend `h` passos depois do último
ponto observado, de modo que os modelos recebem a mesma informação e a
comparação é justa.

## 6. Avaliação (OE2)

`modelos/avaliacao.py` calcula, em núcleos de CPU:

- **MAE e RMSE.**
- **Ganho sobre a persistência:** a persistência prevê que o consumo em `t + h`
  será igual ao de `t`. Ganho positivo indica que o modelo faz mais do que
  repetir o último valor.
- **Atraso estimado:** o deslocamento `k` (0 a h) que maximiza a correlação
  entre previsto e real deslocado. `k ≈ h` indica um modelo que se comporta
  como persistência.
- **Spikes-precision e spikes-recall:** um ponto é pico quando
  `y_k − média > σ·desvio`, calculados sobre a janela anterior de γ pontos, com
  σ = 2 e γ = 250 (Agulló et al., 2025). Pontos consecutivos formam um evento.
  Um pico real conta como antecipado se houver pico previsto entre `h` passos
  antes e 1 passo depois dele.

A LSTM perde 8 pontos a mais que o XGBoost no início do teste (lookback de 20
passos contra 12). Para que todas as estratégias sejam comparadas no mesmo
trecho, a avaliação e o OE3 usam só os pontos comuns aos dois modelos.

Simplificações em relação ao artigo: média e desvio simples (não ponderados) e
sem as tolerâncias de magnitude α/β.

O teste do Perfil B contém um único evento completo, o que deixa
spikes-precision/recall com pouca informação. Por isso, `modelos/antecedencia.py`
mede diretamente quando real e previsto (suavizados por mediana móvel de 5
passos) cruzam 25%, 50% e 75% da amplitude real. Antecedência positiva
significa que a predição subiu antes da carga real.

## 7. Margens de segurança (OE3)

A análise é feita offline, sobre as predições do teste. A alocação de CPU é
`previsto × (1 + m)`, supondo request = limit.

- **Subprovisionamento:** fração dos passos com consumo real acima do alocado.
  Com `limits.cpu`, isso corresponde a throttling.
- **Overprovisioning:** folga média relativa `(alocado − real) / real` nos
  passos sem falta, e também em núcleos.

`modelos/oe3_margens.py` avalia margens de 0, 5, 10, 15 e 20% e procura a
menor que leva o subprovisionamento a no máximo 1% (estrito) ou 5% (tolerante).

`modelos/calibrar_margens.py` evita escolher a margem olhando o próprio teste:
a margem é escolhida na validação (últimos 15% do treino), numa grade de 0 a
200%, e só depois aplicada ao teste. Também reporta o fator de custo (alocado
médio dividido pelo consumo médio) e a margem que seria necessária no teste,
como referência.

Estratégias comparadas:

- **LSTM e XGB:** alocação a partir da predição;
- **REATIVO_SIM:** aloca o valor observado `h` passos antes. Representa uma
  política reativa em que `h` é a latência de provisionamento (cerca de 1 min
  para novos pods e 10 min para novos nós). Não é o HPA executado no cluster;
- **ESTATICO** (só na calibração): alocação fixa, igual ao quantil do consumo
  na validação.

## 8. Limitações

- Ambiente local com um único nó; não representa a latência real de
  provisionamento de um cluster em nuvem.
- A carga é sintética e a forma do Perfil B é uma aproximação linear por
  partes do hidrograma.
- Cada perfil teve uma rodada válida; o teste do Perfil B contém um evento.
- O TensorFlow em CPU pode apresentar pequenas variações entre execuções,
  mesmo com semente fixa.
- O OE3 é avaliado offline sobre as predições. O KEDA está instalado no
  cluster, mas nenhum ScaledObject foi criado: a atuação real do autoscaling
  preditivo e a comparação com o HPA executado no cluster ficam como trabalho
  futuro.
