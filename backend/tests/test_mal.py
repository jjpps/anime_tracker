"""Checagem da integração com o MyAnimeList e do XML. Sem rede.

    python tests/test_mal.py
"""

import os
import sys
import tempfile
import time
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db, export_mal, mal  # noqa: E402
from anime_tracker.progress import progresso_da_temporada  # noqa: E402

SERIE = {
    "series_id": "G1", "series_title": "Mushoku Tensei", "availability": "available",
    "total_episodes": 60, "total_seasons": 3, "added_at": None, "is_favorite": False,
}


class RespostaFalsa:
    def __init__(self, status=200, payload=None, headers=None):
        self.status_code = status
        self._payload = payload or {}
        self.headers = headers or {}
        self.text = str(payload)

    @property
    def ok(self):
        return self.status_code < 400

    def json(self):
        return self._payload


class SessaoFalsa:
    def __init__(self, respostas):
        self.respostas = list(respostas)
        self.urls = []
        self.headers = {}

    def get(self, url, **kw):
        self.urls.append(url)
        return self.respostas.pop(0) if self.respostas else RespostaFalsa(404)


def cliente(respostas, oficial=False):
    c = mal.MALClient("cid" if oficial else None, session=SessaoFalsa(respostas))
    c.intervalo = 0  # o teste não espera de verdade
    return c


def banco():
    conn = db.connect(":memory:")
    db.save_series(conn, [SERIE])
    # contagens coerentes de propósito: a divergência CR x MAL tem teste próprio
    db.save_seasons(conn, "G1", [
        {"season_id": "S1", "season_number": 1, "season_title": "Season 1",
         "total_episodes": 11, "years": (2021, 2022)},
        {"season_id": "S2", "season_number": 2, "season_title": "Season 2",
         "total_episodes": 12, "years": (2023, 2024)},
    ])
    db.save_matches(conn, [
        {"season_id": "S1", "season_number": 1, "anilist_id": 108465,
         "anilist_title": "Mushoku Tensei", "anilist_episodes": 11,
         "anilist_url": "", "confidence": 1.0},
        {"season_id": "S2", "season_number": 2, "anilist_id": 146065,
         "anilist_title": "Mushoku Tensei II", "anilist_episodes": 12,
         "anilist_url": "", "confidence": 1.0},
    ])
    return conn


MAPA = {108465: (39535, "Mushoku Tensei", 11, "TV"),
        146065: (51179, "Mushoku Tensei II", 12, "TV")}


def test_mapa_vem_do_catalogo_e_nao_de_valores_escritos_a_mao():
    """Garante que o par anilist->mal é derivado do arquivo, não digitado.

    Os ids acima são fixture; se divergirem do catálogo real, este teste
    denuncia. Pula quando o catálogo não foi baixado."""
    from anime_tracker.catalog import CatalogoAusente, mapa_anilist_para_mal

    try:
        real = mapa_anilist_para_mal()
    except CatalogoAusente:
        print("   (catálogo ausente, comparação pulada)", end=" ")
        return

    for anilist_id, (mal_id, *_) in MAPA.items():
        assert anilist_id in real, f"anilist {anilist_id} sumiu do catálogo"
        assert real[anilist_id][0] == mal_id, (
            f"fixture diz mal {mal_id}, catálogo diz {real[anilist_id][0]}")

    # e o mapa tem que ser grande: um parser quebrado devolveria quase nada
    assert len(real) > 10000, f"mapa suspeito de estar quebrado: {len(real)} pares"


# --- resolução de ids ---

def test_resolve_mal_id_pelo_catalogo():
    conn = banco()
    r = mal.resolver_ids(conn, MAPA)
    assert r == {"resolvidos": 2, "sem_mapa": 0}
    ids = {x["season_id"]: x["mal_id"] for x in conn.execute("SELECT season_id, mal_id FROM matches")}
    assert ids == {"S1": 39535, "S2": 51179}


def test_anilist_sem_par_no_catalogo_nao_estoura():
    conn = banco()
    r = mal.resolver_ids(conn, {108465: MAPA[108465]})
    assert r == {"resolvidos": 1, "sem_mapa": 1}


def test_rematch_com_outro_anilist_id_descarta_o_mal_id():
    """mal_id foi derivado do anilist_id: se o alvo mudou, ficou obsoleto."""
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.save_matches(conn, [{"season_id": "S1", "season_number": 1, "anilist_id": 999,
                            "anilist_title": "outro", "anilist_episodes": 1,
                            "anilist_url": "", "confidence": 1.0}])
    linha = conn.execute("SELECT mal_id FROM matches WHERE season_id='S1'").fetchone()
    assert linha["mal_id"] is None, "manteria um id apontando para o anime errado"


def test_rematch_com_o_mesmo_anilist_id_preserva_o_mal_id():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.save_matches(conn, [{"season_id": "S1", "season_number": 1, "anilist_id": 108465,
                            "anilist_title": "Mushoku Tensei", "anilist_episodes": 11,
                            "anilist_url": "", "confidence": 1.0}])
    linha = conn.execute("SELECT mal_id FROM matches WHERE season_id='S1'").fetchone()
    assert linha["mal_id"] == 39535, "recasar igual não deveria custar nova resolução"


# --- cliente ---

def test_jikan_le_o_formato_data():
    c = cliente([RespostaFalsa(200, {"data": {"title": "Sousou no Frieren", "episodes": 28}})])
    assert c.anime(52991) == ("Sousou no Frieren", 28)
    assert "jikan" in c.session.urls[0] and c.fonte == "jikan"


def test_api_oficial_quando_ha_client_id():
    c = cliente([RespostaFalsa(200, {"title": "Frieren", "num_episodes": 28})], oficial=True)
    assert c.anime(52991) == ("Frieren", 28)
    assert "myanimelist.net" in c.session.urls[0]
    assert c.session.headers["X-MAL-CLIENT-ID"] == "cid"


def test_chave_vazia_cai_no_jikan():
    """MAL_CLIENT_ID= no .env não pode ser confundido com credencial válida."""
    for valor in ("", None):
        c = mal.MALClient(valor, session=SessaoFalsa([]))
        assert c.oficial is False and c.fonte == "jikan"
        assert "X-MAL-CLIENT-ID" not in c.session.headers


def test_chave_preenchida_troca_a_fonte():
    c = mal.MALClient("abc123", session=SessaoFalsa([]))
    assert c.oficial is True and c.fonte == "myanimelist"
    assert c.session.headers["X-MAL-CLIENT-ID"] == "abc123"
    # a oficial aguenta ritmo maior que o Jikan
    assert c.intervalo < mal.INTERVALO_JIKAN


def test_404_devolve_none_em_vez_de_erro():
    c = cliente([RespostaFalsa(404)])
    assert c.anime(1) is None


def test_504_do_jikan_e_repetido():
    """A busca do Jikan anda devolvendo 504; por id, insistir resolve."""
    dormidas = []
    original, mal.time.sleep = mal.time.sleep, lambda s: dormidas.append(s)
    try:
        c = cliente([RespostaFalsa(504), RespostaFalsa(200, {"data": {"title": "X", "episodes": 12}})])
        assert c.anime(1) == ("X", 12)
        assert dormidas, "deveria pausar antes de repetir"
    finally:
        mal.time.sleep = original


def test_erro_persistente_desiste():
    dormidas = []
    original, mal.time.sleep = mal.time.sleep, lambda s: dormidas.append(s)
    try:
        c = cliente([RespostaFalsa(504) for _ in range(10)])
        c.anime(1)
        raise AssertionError("deveria desistir")
    except mal.MALError as e:
        assert "504" in str(e)
    finally:
        mal.time.sleep = original


# --- double check ---

def test_double_check_aprova_o_que_bate():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    c = cliente([RespostaFalsa(200, {"data": {"title": "Mushoku Tensei", "episodes": 11}}),
                 RespostaFalsa(200, {"data": {"title": "Mushoku Tensei II", "episodes": 12}})])
    rel = mal.double_check(conn, c)
    assert rel["checados"] == 2 and rel["divergentes"] == [], rel["divergentes"]

    linha = conn.execute("SELECT * FROM matches WHERE season_id='S1'").fetchone()
    assert linha["mal_title"] == "Mushoku Tensei" and linha["mal_episodes"] == 11
    assert linha["mal_checked_at"] is not None


def test_double_check_aponta_contagem_divergente():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    c = cliente([RespostaFalsa(200, {"data": {"title": "Outra coisa", "episodes": 99}}),
                 RespostaFalsa(200, {"data": {"title": "Mushoku Tensei II", "episodes": 12}})])
    rel = mal.double_check(conn, c)
    assert len(rel["divergentes"]) == 1
    d = rel["divergentes"][0]
    assert d["season_id"] == "S1" and "11" in d["motivo"] and "99" in d["motivo"]


def test_double_check_aponta_crunchyroll_juntando_o_que_o_mal_separa():
    """Caso real do Mushoku: T1 tem 24 eps na CR e 11 na obra do MAL."""
    conn = banco()
    conn.execute("UPDATE seasons SET total_episodes = 24 WHERE season_id = 'S1'")
    conn.commit()
    mal.resolver_ids(conn, MAPA)
    c = cliente([RespostaFalsa(200, {"data": {"title": "Mushoku Tensei", "episodes": 11}}),
                 RespostaFalsa(200, {"data": {"title": "Mushoku Tensei II", "episodes": 12}})])
    rel = mal.double_check(conn, c)
    assert len(rel["divergentes"]) == 1
    assert rel["divergentes"][0]["motivo"] == "CR tem 24 eps e a obra no MAL tem 11"


def test_double_check_aponta_id_inexistente():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    c = cliente([RespostaFalsa(404), RespostaFalsa(200, {"data": {"title": "Mushoku Tensei II", "episodes": 12}})])
    rel = mal.double_check(conn, c)
    assert len(rel["divergentes"]) == 1
    assert "não existe" in rel["divergentes"][0]["motivo"]


def test_double_check_nao_reconfere_sem_revalidar():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    respostas = [RespostaFalsa(200, {"data": {"title": "Mushoku Tensei", "episodes": 11}}),
                 RespostaFalsa(200, {"data": {"title": "Mushoku Tensei II", "episodes": 12}})]
    mal.double_check(conn, cliente(list(respostas)))

    c = cliente(list(respostas))
    assert mal.double_check(conn, c)["checados"] == 0, "reconferiu à toa"
    assert mal.double_check(conn, cliente(list(respostas)), revalidar=True)["checados"] == 2


def test_double_check_nao_corrige_sozinho():
    """Divergência vira relatório: escolher entre duas fontes é do humano."""
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    c = cliente([RespostaFalsa(200, {"data": {"title": "Outra", "episodes": 99}}),
                 RespostaFalsa(200, {"data": {"title": "Mushoku Tensei II", "episodes": 12}})])
    mal.double_check(conn, c)
    linha = conn.execute("SELECT * FROM matches WHERE season_id='S1'").fetchone()
    assert linha["anilist_id"] == 108465, "o match local não pode ser sobrescrito"
    assert linha["review_status"] == "pending"


# --- progresso e XML ---

def test_progresso_usa_o_maior_episodio():
    # One Piece numera de forma absoluta: contar episódios do arco daria 3
    assert progresso_da_temporada({1171.0, 1172.0, 1173.0}) == 1173


def test_progresso_limita_ao_total_da_obra():
    # CR junta o que o MAL separa: 24 assistidos contra uma obra de 11
    assert progresso_da_temporada(set(range(1, 25)), total_da_obra=11) == 11
    assert progresso_da_temporada(set(), total_da_obra=11) == 0


def test_xml_tem_id_do_mal_preenchido():
    """O exemplo de referência deixa o campo vazio e depende de casar título."""
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.save_history(conn, [
        {"episode_id": f"e{n}", "series_id": "G1", "series_title": "Mushoku Tensei",
         "season_number": 1, "episode_number": float(n), "episode_title": "",
         "watched_at": "2026-01-01T00:00:00Z", "fully_watched": True}
        for n in range(1, 25)
    ])
    caminho = tempfile.mktemp(suffix=".xml")
    r = export_mal.exportar(conn, caminho)

    raiz = ET.parse(caminho).getroot()
    animes = raiz.findall("anime")
    assert r["obras"] == 2 and len(animes) == 2
    ids = [a.findtext("series_animedb_id") for a in animes]
    assert all(i and i.isdigit() for i in ids), ids

    por_id = {a.findtext("series_animedb_id"): a for a in animes}
    t1 = por_id["39535"]
    # 24 assistidos na CR, obra de 11 no MAL: exporta 11, não 24
    assert t1.findtext("my_watched_episodes") == "11"
    assert t1.findtext("my_status") == "Completed"
    assert t1.findtext("update_on_import") == "1"
    assert por_id["51179"].findtext("my_status") == "Plan to Watch"


def test_xml_agrupa_temporadas_na_mesma_obra():
    """One Piece: 24 temporadas na CR, uma obra no MAL — um nó só."""
    conn = banco()
    conn.execute("UPDATE matches SET mal_id = 21, mal_episodes = 1168, "
                 "mal_title = 'One Piece'")
    conn.commit()
    db.save_history(conn, [
        {"episode_id": "a", "series_id": "G1", "series_title": "One Piece",
         "season_number": 1, "episode_number": 60.0, "episode_title": "",
         "watched_at": "2026-01-01T00:00:00Z", "fully_watched": True},
        {"episode_id": "b", "series_id": "G1", "series_title": "One Piece",
         "season_number": 2, "episode_number": 1173.0, "episode_title": "",
         "watched_at": "2026-01-02T00:00:00Z", "fully_watched": True},
    ])
    caminho = tempfile.mktemp(suffix=".xml")
    r = export_mal.exportar(conn, caminho)

    animes = ET.parse(caminho).getroot().findall("anime")
    assert len(animes) == 1, "duas entradas com o mesmo id brigariam no import"
    assert r["obras"] == 1 and r["temporadas"] == 2
    # vence o maior progresso (1173 do arco recente, não 60), limitado ao
    # total que o MAL declara para a obra
    assert animes[0].findtext("my_watched_episodes") == "1168"


def test_xml_ignora_rejeitados():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.set_review(conn, "S1", "rejected")
    caminho = tempfile.mktemp(suffix=".xml")
    assert export_mal.exportar(conn, caminho)["obras"] == 1


def test_xml_so_confirmados():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.set_review(conn, "S1", "confirmed")
    caminho = tempfile.mktemp(suffix=".xml")
    assert export_mal.exportar(conn, caminho, apenas_confirmados=True)["obras"] == 1


def test_xml_sem_mal_id_fica_de_fora():
    """Sem id, o import cairia no casamento por título — melhor não exportar."""
    conn = banco()
    caminho = tempfile.mktemp(suffix=".xml")
    assert export_mal.exportar(conn, caminho)["obras"] == 0


def test_status_de():
    assert export_mal.status_de(0, 12) == "Plan to Watch"
    assert export_mal.status_de(5, 12) == "Watching"
    assert export_mal.status_de(12, 12) == "Completed"
    assert export_mal.status_de(5, 0) == "Watching"  # sem total, não afirma completo


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
