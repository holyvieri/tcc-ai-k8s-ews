"""
Perfil B: pico de emergência (evento de cheia).

Cada ciclo tem rotina, subida, platô e decaimento. A proporção entre as fases
vem do hidrograma do GloFAS (bacia do Douro, previsão de 13/11/2026: ~3,5 dias
de subida, ~3 de pico e ~7 de recessão), comprimido para 1 dia = 6 min. A
intensidade do pico (10x a rotina) vem da literatura de flash crowd. A rotina
usa os mesmos 30 usuários do Perfil A.

Uso:
    locust -f locust/perfil_b.py --host http://localhost:8080 --headless --csv dados/locust_perfil_b

Calibração rápida do pico (4 min, com o coletor ligado):
    $env:CALIBRACAO = "1"; locust -f locust/perfil_b.py --host http://localhost:8080 --headless
"""
import os
import random

from locust import FastHttpUser, LoadTestShape, between, task

USUARIOS_ROTINA = 30     # mesmo nível do Perfil A
USUARIOS_PICO = 300      # 10:1 em relação à rotina
ROTINA_MIN = 30          # minutos de rotina antes do pico
SUBIDA_MIN = 21          # 3,5 dias x 6 min
SUSTENTACAO_MIN = 18     # 3 dias x 6 min
DECAIMENTO_MIN = 42      # 7 dias x 6 min
CICLOS = 3               # vários picos para sobrar ao menos um no teste

PRODUTOS = [
    "0PUK6V6EV0", "1YMWWN1N4O", "2ZYFJ3GM2N", "66VCHSJNUP", "6E92ZMYYFZ",
    "9SIQT8TOJO", "L9ECAV7KIM", "LS4PSXUNUM", "OLJCESPC7Z",
]


class UsuarioEmergencia(FastHttpUser):
    # na emergência o usuário basicamente consulta a página repetidas vezes,
    # sem checkout (premissa do trabalho, não vem do benchmark)
    wait_time = between(1, 10)

    def on_start(self):
        self.client.get("/")

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
    # trapézio: rotina -> subida -> platô -> decaimento, repetido CICLOS vezes
    def tick(self):
        # calibração: 1 min de rotina e 3 min no pico
        if os.environ.get("CALIBRACAO"):
            t = self.get_run_time()
            if t > 240:
                return None
            return (USUARIOS_ROTINA if t < 60 else USUARIOS_PICO, 50)

        ciclo_s = (ROTINA_MIN + SUBIDA_MIN + SUSTENTACAO_MIN + DECAIMENTO_MIN) * 60
        t_total = self.get_run_time()
        if t_total > CICLOS * ciclo_s:
            return None

        t = t_total % ciclo_s
        rotina_s = ROTINA_MIN * 60
        subida_s = SUBIDA_MIN * 60
        sustent_s = SUSTENTACAO_MIN * 60

        if t < rotina_s:
            usuarios = USUARIOS_ROTINA
        elif t < rotina_s + subida_s:
            frac = (t - rotina_s) / subida_s
            usuarios = USUARIOS_ROTINA + frac * (USUARIOS_PICO - USUARIOS_ROTINA)
        elif t < rotina_s + subida_s + sustent_s:
            usuarios = USUARIOS_PICO
        else:
            frac = (t - rotina_s - subida_s - sustent_s) / (DECAIMENTO_MIN * 60)
            usuarios = USUARIOS_PICO - frac * (USUARIOS_PICO - USUARIOS_ROTINA)

        return (max(1, round(usuarios)), 50)