"""
Perfil A: carga de rotina de um EWS fora de emergência.

O comportamento do usuário (tarefas, pesos e think time de 1 a 10 s) segue o
locustfile oficial da Online Boutique. A quantidade de usuários oscila de forma
senoidal em torno de uma base, com um pouco de ruído.

Uso:
    kubectl port-forward svc/frontend 8080:80
    locust -f locust/perfil_a.py --host http://localhost:8080 --headless --csv dados/locust_perfil_a
"""
import math
import random

from locust import FastHttpUser, LoadTestShape, TaskSet, between, task

USUARIOS_BASE = 30      # nível médio de usuários simultâneos
AMPLITUDE = 10          # oscilação em torno da base
PERIODO_MIN = 20        # 2x o maior horizonte de predição (10 min)
DURACAO_MIN = 340

PRODUTOS = [
    "0PUK6V6EV0", "1YMWWN1N4O", "2ZYFJ3GM2N", "66VCHSJNUP", "6E92ZMYYFZ",
    "9SIQT8TOJO", "L9ECAV7KIM", "LS4PSXUNUM", "OLJCESPC7Z",
]
MOEDAS = ["EUR", "USD", "JPY", "CAD", "GBP", "TRY"]


class ComportamentoRotina(TaskSet):
    def on_start(self):
        self.client.get("/")

    @task(1)
    def index(self):
        self.client.get("/")

    @task(2)
    def set_currency(self):
        self.client.post("/setCurrency", {"currency_code": random.choice(MOEDAS)})

    @task(10)
    def browse_product(self):
        self.client.get(f"/product/{random.choice(PRODUTOS)}")

    @task(2)
    def add_to_cart(self):
        produto = random.choice(PRODUTOS)
        self.client.get(f"/product/{produto}")
        self.client.post("/cart", {"product_id": produto, "quantity": random.randint(1, 10)})

    @task(3)
    def view_cart(self):
        self.client.get("/cart")

    @task(1)
    def checkout(self):
        self.add_to_cart()
        self.client.post("/cart/checkout", {
            "email": "teste@exemplo.com",
            "street_address": "Rua Exemplo 123",
            "zip_code": "55290000",
            "city": "Garanhuns",
            "state": "PE",
            "country": "Brazil",
            "credit_card_number": "4432801561520454",  # cartão de teste da demo
            "credit_card_expiration_month": random.randint(1, 12),
            "credit_card_expiration_year": 2030,
            "credit_card_cvv": f"{random.randint(100, 999)}",
        })


class UsuarioBoutique(FastHttpUser):
    tasks = [ComportamentoRotina]
    wait_time = between(1, 10)


class CargaRotineira(LoadTestShape):
    # usuarios(t) = base + amplitude * sen(2*pi*t / periodo) + ruído
    def tick(self):
        t = self.get_run_time()
        if t > DURACAO_MIN * 60:
            return None

        onda = AMPLITUDE * math.sin(2 * math.pi * t / (PERIODO_MIN * 60))
        ruido = random.randint(-3, 3)
        usuarios = max(1, round(USUARIOS_BASE + onda + ruido))
        return (usuarios, 10)