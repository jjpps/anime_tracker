"""Checagem da API. Banco temporário, sem rede.

    python tests/test_server.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


from anime_tracker import db, sync  # noqa: E402
from anime_tracker.server import create_app  # noqa: E402

SERIE = {"series_id": "G1", "series_title": "Mushoku Tensei", "availability": "available",
         "total_episodes": 36, "total_seasons": 2}


def app_com_dados():
    """Viu a temporada 1 inteira; a 2 já está na CR."""
    caminho = tempfile.mktemp(suffix=".db")
    conn = db.connect(caminho)
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, "G1", [
        {"season_id": "S1", "season_number": 1, "season_title": "Season 1",
         "total_episodes": 1, "episodes": [{"episode_number": 1.0, "released_at": None}]},
        {"season_id": "S2", "season_number": 2, "season_title": "Season 2",
         "total_episodes": 12, "episodes": []},
    ])
    db.save_history(conn, [{"episode_id": "e1", "series_id": "G1", "series_title": "Mushoku Tensei",
                            "season_number": 1, "episode_number": 1.0, "episode_title": "",
                            "watched_at": "2025-01-01T00:00:00Z", "fully_watched": True}])
    conn.close()
    app = create_app(caminho)
    app.config["TESTING"] = True
    return app.test_client(), caminho


def test_stats():
    cli, _ = app_com_dados()
    s = cli.get("/api/stats").get_json()
    assert (s["series"], s["seasons"], s["episodes"]) == (1, 2, 1)


def test_novidades():
    cli, _ = app_com_dados()
    [a] = cli.get("/api/novidades").get_json()
    assert a["title"] == "Mushoku Tensei"
    assert a["new_seasons"] == [{"title": "Season 2", "episodes": 12}]


def test_status_da_tarefa_traz_o_erro_do_sync():
    cli, caminho = app_com_dados()
    s = cli.get("/api/task").get_json()
    assert s["rodando"] is False and s["ultimo_sync"] is None and s["erro_sync"] is None

    conn = db.connect(caminho)
    db.set_setting(conn, sync.ULTIMO_ERRO, "auth falhou")
    conn.close()
    assert cli.get("/api/task").get_json()["erro_sync"] == "auth falhou"


def test_frontend_servido():
    """Com build presente serve o bundle; sem build, instrui em vez de 404."""
    cli, _ = app_com_dados()
    r = cli.get("/")
    if r.status_code == 503:
        assert b"npm run build" in r.data
    else:
        assert r.status_code == 200 and b"<app-root" in r.data


def test_rota_desconhecida_cai_no_angular():
    """O roteador é do Angular: caminho sem arquivo devolve o index, não 404."""
    cli, _ = app_com_dados()
    assert cli.get("/biblioteca").status_code in (200, 503)


def test_baixar_crunchyroll_exige_cookie():
    cli, _ = app_com_dados()
    anterior = os.environ.pop("CR_ETP_RT", None)
    try:
        r = cli.post("/api/crunchyroll", json={"force": True})
        assert r.status_code == 500 and "CR_ETP_RT" in r.get_json()["erro"]
    finally:
        if anterior is not None:
            os.environ["CR_ETP_RT"] = anterior


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
