"""Checagem da API e do callback OAuth. Banco temporário, sem rede.

    python tests/test_server.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db, oauth  # noqa: E402
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


def test_menus_separam_revisado_de_pendente():
    cli, caminho = app_com_dados()
    assert len(cli.get("/api/pending").get_json()) == 2
    assert cli.get("/api/catalog").get_json() == []

    r = cli.post("/api/review/S1", json={"status": "confirmed"})
    assert r.status_code == 200

    pendentes = cli.get("/api/pending").get_json()
    catalogo = cli.get("/api/catalog").get_json()
    assert [x["season_id"] for x in pendentes] == ["S3"]
    assert [x["season_id"] for x in catalogo] == ["S1"]
    assert catalogo[0]["series_title"] == "Mushoku Tensei"


def test_confirmar_corrigindo_o_id():
    cli, _ = app_com_dados()
    cli.post("/api/review/S3", json={"status": "confirmed", "anilist_id": 999})
    assert cli.get("/api/catalog").get_json()[0]["anilist_id"] == 999


def test_reabrir_volta_para_pendente():
    cli, _ = app_com_dados()
    cli.post("/api/review/S1", json={"status": "confirmed"})
    cli.post("/api/review/S1", json={"status": "pending"})
    assert cli.get("/api/catalog").get_json() == []
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


def test_frontend_servido():
    cli, _ = app_com_dados()
    r = cli.get("/")
    assert r.status_code == 200 and b"Cat\xc3\xa1logo sincronizado" in r.data


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
