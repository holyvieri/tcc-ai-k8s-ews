"""
Perfil B - PICO DE EMERGÊNCIA (Locust)

Simula o padrão de um EWS durante um evento de cheia: carga baixa de rotina,
subida ABRUPTA quando o alerta dispara (população acessando ao mesmo tempo),
sustentação do pico, decaimento gradual.

CALIBRAÇÃO TEMPORAL (GloFAS):
  Fonte: GloFAS / Copernicus EMS, hidrograma IFS ENS do ponto DM000831,
  bacia do Douro (Espanha), previsão de 13/11/2026 (acesso em 13/11/2026).
  Leitura da mediana (passos diários):
    subida   ~3,5 dias  (base -> pico)
    pico     ~3   dias  (mediana >= 90% do máximo)
    recessão ~7   dias  (até cair abaixo do limiar de 2 anos)
  Proporção ~3,5 : 3 : 7 -> compressão 1 dia = 6 min -> 21 / 18 / 42 min.
  Do GloFAS vem SÓ a forma temporal. A intensidade (10:1) vem da literatura
  de flash crowd - não há relação conhecida entre vazão e acessos ao sistema.
  As fases são aproximadas por segmentos lineares (simplificação declarada).

Como rodar:
    kubectl port-forward svc/frontend 8080:80
    locust -f locust/perfil_b.py --host http://localhost:8080 --headless --csv dados/locust_perfil_b
"""
import random

from locust import FastHttpUser, LoadTestShape, between, task

# ------------- parâmetros do pico (calibrados c/ GloFAS) -------------
USUARIOS_ROTINA = 15     # carga de base antes do evento
USUARIOS_PICO = 150      # auge do evento (10:1 - literatura de flash crowd)
ROTINA_MIN = 30          # minutos de rotina antes do pico
SUBIDA_MIN = 21          # GloFAS: ~3,5 dias de subida x 6 min/dia
SUSTENTACAO_MIN = 18     # GloFAS: ~3 dias de pico x 6 min/dia
DECAIMENTO_MIN = 42      # GloFAS: ~7 dias de recessão x 6 min/dia
CICLOS = 3               # repete o ciclo (rotina->pico->decaimento) N vezes
# -------------------------------------------------------------------

# IDs de produto da Online Boutique
PRODUTOS = [
    "0PUK6V6EV0", "1YMWWN1N4O", "2ZYFJ3GM2N", "66VCHSJNUP", "6E92ZMYYFZ",
    "9SIQT8TOJO", "L9ECAV7KIM", "LS4PSXUNUM", "OLJCESPC7Z",
]


class UsuarioEmergencia(FastHttpUser):
    """PREMISSA DECLARADA (não vem do benchmark): durante a emergência o padrão
    muda para consulta repetida de status - quase só home/produto, sem
    checkout - análogo à população checando o alerta. Cliente FastHttpUser,
    o mesmo do Perfil A, para que a diferença entre perfis venha da carga e
    não do cliente HTTP."""

    wait_time = between(1, 2)  # think time curto: premissa de urgência (declarada)

    def on_start(self):
        self.client.get("/")  # entrada pela home, como no locustfile oficial

    @task(15)
    def home(self):
        self.client.get("/")

    @task(5)
    def ver_produto(self):
        self.client.get(f"/product/{random.choice(PRODUTOS)}")

    @task(1)
    def adicionar_carrinho(self):
        self.client.post(
            "/cart",
            data={"product_id": random.choice(PRODUTOS), "quantity": 1},
        )


class CargaPico(LoadTestShape):
    """Trapézio de carga: rotina -> rampa de subida -> platô -> decaimento.

    Repete CICLOS vezes para gerar vários picos na série temporal — o modelo
    precisa ver mais de um pico no treino para aprender o padrão (e sobrar
    pelo menos um pico inteiro no bloco de teste).
    """

    def tick(self):
        ciclo_s = (ROTINA_MIN + SUBIDA_MIN + SUSTENTACAO_MIN + DECAIMENTO_MIN) * 60
        t_total = self.get_run_time()
        if t_total > CICLOS * ciclo_s:
            return None  # encerra

        t = t_total % ciclo_s  # posição dentro do ciclo atual
        rotina_s = ROTINA_MIN * 60
        subida_s = SUBIDA_MIN * 60
        sustent_s = SUSTENTACAO_MIN * 60

        if t < rotina_s:
            usuarios = USUARIOS_ROTINA
        elif t < rotina_s + subida_s:
            # rampa linear da rotina ao pico
            frac = (t - rotina_s) / subida_s
            usuarios = USUARIOS_ROTINA + frac * (USUARIOS_PICO - USUARIOS_ROTINA)
        elif t < rotina_s + subida_s + sustent_s:
            usuarios = USUARIOS_PICO
        else:
            # decaimento linear de volta à rotina
            frac = (t - rotina_s - subida_s - sustent_s) / (DECAIMENTO_MIN * 60)
            usuarios = USUARIOS_PICO - frac * (USUARIOS_PICO - USUARIOS_ROTINA)

        return (max(1, round(usuarios)), 50)