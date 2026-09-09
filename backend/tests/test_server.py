"""Checagem da API e do callback OAuth. Banco temporário, sem rede.

    python tests/test_server.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone  # noqa: E402

from anime_tracker import db, oauth, sync  # noqa: E402
from anime_tracker.server import create_app  # noqa: E402

SERIE = {
    "series_id": "G1", "series_title": "Mushoku Tensei", "availability": "available",
    "total_episodes": 60, "total_seasons": 3, "added_at": "2023-08-05T15:16:35Z",
    "is_favorite": False,
}


def app_com_dados():
    caminho = tempfile.mktemp(suffix=".db")
    conn = db.connect(caminho)
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, "G1", [
        {"season_id": "S1", "season_number": 1, "season_title": "Season 1",
         "total_episodes": 24, "years": (2021, 2022)},
        {"season_id": "S3", "season_number": 3, "season_title": "Season 3",
         "total_episodes": 11, "years": (2026, 2026)},
    ])
    db.save_matches(conn, [
        {"season_id": "S1", "season_number": 1, "anilist_id": 108465,
         "anilist_title": "Mushoku Tensei", "anilist_episodes": 11,
         "anilist_url": "", "confidence": 1.0},
        {"season_id": "S3", "season_number": 3, "anilist_id": 166873,
         "anilist_title": "Mushoku Tensei III", "anilist_episodes": 14,
         "anilist_url": "", "confidence": 0.8},
    ])
    conn.close()
    app = create_app(caminho)
    app.config["TESTING"] = True
    return app.test_client(), caminho


def test_menu_catalogo_mostra_tudo_que_tem_match():
    """Menu 1 = match resolvido, revisado ou não; menu 2 = só o que falta decidir."""
    cli, _ = app_com_dados()
    assert len(cli.get("/api/catalog").get_json()) == 2, "match resolvido já entra no catálogo"
    assert len(cli.get("/api/pending").get_json()) == 2

    assert cli.post("/api/review/S1", json={"status": "confirmed"}).status_code == 200

    catalogo = cli.get("/api/catalog").get_json()
    pendentes = cli.get("/api/pending").get_json()
    assert len(catalogo) == 2, "revisar não tira do catálogo"
    assert [x["season_id"] for x in pendentes] == ["S3"], "revisado sai da fila"
    assert {x["season_id"]: x["review_status"] for x in catalogo} == {
        "S1": "confirmed", "S3": "pending"}


def test_catalogo_ignora_temporada_sem_match():
    cli, caminho = app_com_dados()
    conn = db.connect(caminho)
    conn.execute("UPDATE matches SET anilist_id = NULL WHERE season_id = 'S1'")
    conn.commit()
    conn.close()
    assert [x["season_id"] for x in cli.get("/api/catalog").get_json()] == ["S3"]


def test_confirmar_corrigindo_o_id():
    cli, _ = app_com_dados()
    cli.post("/api/review/S3", json={"status": "confirmed", "anilist_id": 999})
    por_id = {x["season_id"]: x for x in cli.get("/api/catalog").get_json()}
    assert por_id["S3"]["anilist_id"] == 999


def test_reabrir_volta_para_pendente():
    cli, _ = app_com_dados()
    cli.post("/api/review/S1", json={"status": "confirmed"})
    cli.post("/api/review/S1", json={"status": "pending"})
    assert len(cli.get("/api/pending").get_json()) == 2


def test_entradas_invalidas():
    cli, _ = app_com_dados()
    assert cli.post("/api/review/S1", json={"status": "talvez"}).status_code == 400
    assert cli.post("/api/review/S1", json={"status": "confirmed", "anilist_id": "abc"}).status_code == 400
    assert cli.post("/api/review/NAOEXISTE", json={"status": "confirmed"}).status_code == 404
    assert cli.post("/api/review/S1", json={}).status_code == 400


def test_filtro_por_serie():
    cli, _ = app_com_dados()
    assert len(cli.get("/api/pending?q=mushoku").get_json()) == 2
    assert cli.get("/api/pending?q=one piece").get_json() == []


def test_stats():
    cli, _ = app_com_dados()
    s = cli.get("/api/stats").get_json()
    assert s["pending"] == 2 and s["confirmed"] == 0
    assert s["anilist_conectado"] is False
    assert "catalogo_local" in s, "a UI precisa saber se dá para casar offline"


def test_callback_recusa_state_errado():
    """Sem conferir o state, qualquer página poderia disparar a troca do code."""
    cli, caminho = app_com_dados()
    conn = db.connect(caminho)
    db.set_setting(conn, oauth.STATE_KEY, "state-correto")
    conn.close()

    r = cli.get("/auth/anilist/callback?code=abc&state=state-errado")
    assert r.status_code == 400
    assert "state" in r.get_json()["erro"]

    conn = db.connect(caminho)
    assert db.get_setting(conn, oauth.TOKEN_KEY) is None, "token não pode ser gravado"
    conn.close()


def test_callback_sem_code():
    cli, _ = app_com_dados()
    assert cli.get("/auth/anilist/callback?error=access_denied").status_code == 400


def test_authorize_url():
    url = oauth.authorize_url("123", "http://localhost:8000/cb", "xyz")
    assert url.startswith(oauth.AUTHORIZE + "?")
    assert "client_id=123" in url and "response_type=code" in url and "state=xyz" in url
    assert "redirect_uri=http%3A%2F%2Flocalhost%3A8000%2Fcb" in url


def test_sync_respeita_ttl():
    """Botão + TTL: clique repetido não pode disparar sync de novo."""
    cli, caminho = app_com_dados()
    conn = db.connect(caminho)
    db.set_setting(conn, sync.ULTIMO_SYNC,
                   datetime.now(timezone.utc).isoformat(timespec="seconds"))
    conn.close()

    r = cli.post("/api/sync", json={})
    assert r.status_code == 429
    assert r.get_json()["minutos_ate_liberar"] > 0

    assert cli.get("/api/task").get_json()["rodando"] is False


def test_sync_sem_credencial_nao_inicia():
    cli, _ = app_com_dados()
    anterior = os.environ.pop("CR_ETP_RT", None)
    try:
        r = cli.post("/api/sync", json={"force": True})
        assert r.status_code == 500 and "CR_ETP_RT" in r.get_json()["erro"]
    finally:
        if anterior is not None:
            os.environ["CR_ETP_RT"] = anterior


def test_status_da_tarefa():
    cli, _ = app_com_dados()
    s = cli.get("/api/task").get_json()
    assert s["rodando"] is False and s["ultimo_sync"] is None and s["tipo"] is None


def test_botao_match_roda_sozinho():
    """O match tem botão próprio: não exige sincronizar antes."""
    cli, caminho = app_com_dados()
    conn = db.connect(caminho)
    conn.execute("DELETE FROM matches")
    conn.commit()
    conn.close()

    r = cli.post("/api/match", json={})
    assert r.status_code == 202

    for _ in range(100):
        s = cli.get("/api/task").get_json()
        if not s["rodando"]:
            break
        time.sleep(0.1)
    assert s["tipo"] == "match"
    # sem AniList nem catálogo o match não roda, mas não pode estourar
    assert s["erro"] is None, s["erro"]
    assert s["resultado"] is not None


def test_match_nao_exige_credencial_da_crunchyroll():
    cli, _ = app_com_dados()
    anterior = os.environ.pop("CR_ETP_RT", None)
    try:
        assert cli.post("/api/match", json={}).status_code == 202
    finally:
        if anterior is not None:
            os.environ["CR_ETP_RT"] = anterior


def test_stats_distingue_banco_vazio():
    """A UI usa series/matched para dizer QUAL etapa falta em vez de 'nada'."""
    import tempfile as _tmp

    caminho = _tmp.mktemp(suffix=".db")
    db.connect(caminho).close()
    app = create_app(caminho)
    app.config["TESTING"] = True
    vazio = app.test_client().get("/api/stats").get_json()
    assert vazio["series"] == 0 and vazio["matched"] == 0

    com_dados = app_com_dados()[0].get("/api/stats").get_json()
    assert com_dados["series"] == 1 and com_dados["matched"] == 2


def _esperar(cli, tentativas=100):
    for _ in range(tentativas):
        s = cli.get("/api/task").get_json()
        if not s["rodando"]:
            return s
        time.sleep(0.1)
    raise AssertionError("tarefa não terminou")


def test_botao_mal_roda_a_tarefa():
    """Botão Sincronizar MyAnimeList: resolve ids e confere, em background."""
    cli, _ = app_com_dados()
    r = cli.post("/api/mal", json={})
    assert r.status_code == 202

    s = _esperar(cli)
    assert s["tipo"] == "mal"
    # sem catálogo local a tarefa falha com instrução, sem derrubar o servidor
    if s["erro"]:
        assert "catálogo local" in s["erro"] or "CatalogoAusente" in s["erro"]
    else:
        assert "resolvidos" in s["resultado"] and "fonte" in s["resultado"]


def test_mal_nao_roda_junto_com_outra_tarefa():
    """Sync e MAL mexem nas mesmas tabelas: uma de cada vez."""
    cli, _ = app_com_dados()
    cli.post("/api/mal", json={})
    segunda = cli.post("/api/mal", json={})
    # ou a primeira já terminou (202) ou a segunda é recusada (409)
    assert segunda.status_code in (202, 409)
    if segunda.status_code == 409:
        assert "andamento" in segunda.get_json()["erro"]
    _esperar(cli)


def test_stats_traz_contadores_do_mal():
    cli, _ = app_com_dados()
    s = cli.get("/api/stats").get_json()
    assert s["com_mal_id"] == 0 and s["mal_conferidos"] == 0


def test_botao_mal_aparece_no_frontend():
    cli, _ = app_com_dados()
    html = cli.get("/").data.decode()
    assert 'id="mal"' in html
    assert '/api/mal' in html


def test_frontend_servido():
    cli, _ = app_com_dados()
    r = cli.get("/")
    assert r.status_code == 200 and b"Cat\xc3\xa1logo sincronizado" in r.data


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
