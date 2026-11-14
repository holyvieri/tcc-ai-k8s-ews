"""
Perfil A - Carga ROTINEIRA (Locust)

Simula o dia a dia de um EWS fora de emergência: monitoramento constante,
consultas regulares, variação suave.

PROVENIÊNCIA DOS PARÂMETROS:
  - Comportamento do usuário (ações, pesos e think time): ESPELHA o gerador de
    carga oficial da Online Boutique (src/loadgenerator/locustfile.py, Google
    LLC, 2018): index:1, setCurrency:2, browseProduct:10, addToCart:2,
    viewCart:3, checkout:1; wait_time = between(1, 10).
    Única diferença: dados de checkout fixos em vez da lib Faker (não altera a
    carga no servidor; evita dependência extra).
  - Forma da carga (nível médio + oscilação periódica + ruído): caracterização
    clássica de tráfego web de rotina (periodicidade + variação estocástica).
  - USUARIOS_BASE, AMPLITUDE, PERIODO_MIN, DURACAO_MIN: escolhas de projeto
    declaradas - dimensionadas ao cluster Kind local e aos horizontes de
    predição (PERIODO_MIN = 2x o maior horizonte, 10 min).

Como rodar (com o port-forward do frontend ativo em localhost:8080):
    kubectl port-forward svc/frontend 8080:80
    locust -f locust/perfil_a.py --host http://localhost:8080 --headless --csv dados/locust_perfil_a
"""
import math
import random

from locust import FastHttpUser, LoadTestShape, TaskSet, between, task

# ------------------- parâmetros do perfil (escolhas de projeto) -------------------
USUARIOS_BASE = 30      # nível médio de usuários simultâneos
AMPLITUDE = 10          # oscilação em torno da base (+-33%)
PERIODO_MIN = 20        # período da oscilação (2x o maior horizonte de predição)
DURACAO_MIN = 360       # duração total (6h -> ~1440 pontos a 15s)
# ---------------------------------------------------------------------------------

# IDs de produto da Online Boutique
PRODUTOS = [
    "0PUK6V6EV0", "1YMWWN1N4O", "2ZYFJ3GM2N", "66VCHSJNUP", "6E92ZMYYFZ",
    "9SIQT8TOJO", "L9ECAV7KIM", "LS4PSXUNUM", "OLJCESPC7Z",
]
MOEDAS = ["EUR", "USD", "JPY", "CAD", "GBP", "TRY"]


class ComportamentoRotina(TaskSet):
    """Ações e pesos idênticos ao locustfile oficial da Boutique."""

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
            "credit_card_number": "4432801561520454",  # cartão fake da própria demo
            "credit_card_expiration_month": random.randint(1, 12),
            "credit_card_expiration_year": 2030,
            "credit_card_cvv": f"{random.randint(100, 999)}",
        })


class UsuarioBoutique(FastHttpUser):
    tasks = [ComportamentoRotina]
    wait_time = between(1, 10)  # think time do locustfile oficial


class CargaRotineira(LoadTestShape):
    """Define QUANTOS usuários existem a cada instante.

    tick() é chamado ~1x/segundo pelo Locust e devolve (usuarios, taxa_spawn).
    usuarios(t) = BASE + AMPLITUDE * sen(2*pi*t / PERIODO) + ruído.
    """

    def tick(self):
        t = self.get_run_time()  # segundos desde o início
        if t > DURACAO_MIN * 60:
            return None  # encerra o teste

        onda = AMPLITUDE * math.sin(2 * math.pi * t / (PERIODO_MIN * 60))
        ruido = random.randint(-3, 3)
        usuarios = max(1, round(USUARIOS_BASE + onda + ruido))
        return (usuarios, 10)