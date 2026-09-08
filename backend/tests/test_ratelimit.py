"""Checagem do rate limiting do AniList. Sessão falsa, sem rede e sem dormir.

Regras da doc: 90 req/min (30 no estado degradado), headers X-RateLimit-*,
429 traz Retry-After e X-RateLimit-Reset.

    python tests/test_ratelimit.py
"""

import os
import sys
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import anilist  # noqa: E402
from anime_tracker.anilist import MAX_TENTATIVAS, AniList, AniListError  # noqa: E402


class RespostaFalsa:
    def __init__(self, status=200, headers=None, payload=None):
        self.status_code = status
        self.headers = headers or {}
        self._payload = payload if payload is not None else {"data": {"ok": 1}}
        self.content = b"x"
        self.text = str(self._payload)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._payload


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.chamadas = 0
        self.headers = {}

    def post(self, *a, **kw):
        self.chamadas += 1
        return self.respostas.pop(0) if self.respostas else RespostaFalsa()


ERRO_429 = {"data": None, "errors": [{"message": "Too Many Requests.", "status": 429}]}


def cliente(respostas, dormidas):
    """Cliente com sessão falsa e sleep instrumentado."""
    c = AniList(cache_path="/tmp/nao-existe-cache.json")
    c.session = SessaoFalsa(respostas)
    anilist.time.sleep = lambda s: dormidas.append(s)
    return c


def restaurar():
    anilist.time.sleep = time.sleep


def test_aprende_o_limite_pelos_headers():
    """O limite muda (90 normal, 30 degradado): seguir o header, não um fixo."""
    dormidas = []
    c = cliente([RespostaFalsa(headers={"X-RateLimit-Limit": "90",
                                        "X-RateLimit-Remaining": "59"})], dormidas)
    try:
        c._post("{}", {})
        assert c.limite == 90 and c.restante == 59
    finally:
        restaurar()


def test_espaca_chamadas_conforme_o_limite():
    dormidas = []
    c = cliente([RespostaFalsa(headers={"X-RateLimit-Limit": "30", "X-RateLimit-Remaining": "29"}),
                 RespostaFalsa(headers={"X-RateLimit-Limit": "30", "X-RateLimit-Remaining": "28"})],
                dormidas)
    try:
        c._post("{}", {})
        c._post("{}", {})   # a segunda tem que esperar 60/30 = 2s
        assert dormidas and 1.5 <= dormidas[0] <= 2.0, dormidas
    finally:
        restaurar()


def test_sem_headers_usa_o_padrao_degradado():
    dormidas = []
    c = cliente([RespostaFalsa(), RespostaFalsa()], dormidas)
    try:
        c._post("{}", {})
        assert c.limite == 30, "sem header, mantém o palpite conservador"
        assert c.restante is None
        c._post("{}", {})
        assert dormidas and dormidas[0] > 1.5
    finally:
        restaurar()


def test_429_respeita_retry_after():
    dormidas = []
    c = cliente([
        RespostaFalsa(429, {"Retry-After": "30", "X-RateLimit-Reset": "1502035959"}, ERRO_429),
        RespostaFalsa(),
    ], dormidas)
    try:
        assert c._post("{}", {}) == {"ok": 1}, "deveria repetir e ter sucesso"
        assert 30 in dormidas, dormidas
        assert c.session.chamadas == 2
    finally:
        restaurar()


def test_429_sem_retry_after_usa_o_reset():
    dormidas = []
    reset = int(time.time()) + 45
    c = cliente([RespostaFalsa(429, {"X-RateLimit-Reset": str(reset)}, ERRO_429),
                 RespostaFalsa()], dormidas)
    try:
        c._post("{}", {})
        assert any(40 <= d <= 46 for d in dormidas), dormidas
    finally:
        restaurar()


def test_429_sem_header_nenhum_espera_um_minuto():
    dormidas = []
    c = cliente([RespostaFalsa(429, {}, ERRO_429), RespostaFalsa()], dormidas)
    try:
        c._post("{}", {})
        assert 60 in dormidas, dormidas
    finally:
        restaurar()


def test_429_persistente_desiste_em_vez_de_travar():
    """Sem teto, um 429 permanente prenderia a thread do servidor para sempre."""
    dormidas = []
    c = cliente([RespostaFalsa(429, {"Retry-After": "1"}, ERRO_429) for _ in range(10)], dormidas)
    try:
        c._post("{}", {})
        raise AssertionError("deveria desistir")
    except AniListError as e:
        assert "rate limit persistente" in str(e)
        assert c.session.chamadas == MAX_TENTATIVAS, c.session.chamadas
    finally:
        restaurar()


def test_erro_graphql_com_200_ainda_e_erro():
    """A API devolve erro no corpo mesmo com HTTP 200."""
    dormidas = []
    c = cliente([RespostaFalsa(200, {}, {"data": None, "errors": [{"message": "boom"}]})], dormidas)
    try:
        c._post("{}", {})
        raise AssertionError("deveria levantar")
    except AniListError as e:
        assert "boom" in str(e)
    finally:
        restaurar()


def test_disponivel_nao_estoura_com_403():
    dormidas = []
    c = cliente([RespostaFalsa(403, {}, {"data": None,
                                         "errors": [{"message": "temporarily disabled"}]})], dormidas)
    try:
        assert c.disponivel() is False
    finally:
        restaurar()


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
