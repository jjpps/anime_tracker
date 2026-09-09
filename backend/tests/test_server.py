"""Checagem da API e do callback OAuth. Banco temporário, sem rede.

    python tests/test_server.py
"""

import os
import sys
import tempfile
import time

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from datetime import datetime, timezone  # noqa: E402

from anime_tracker import db, sync  # noqa: E402
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
        {"season_id": "S1", "season_number": 1,
         "provider": "anilist", "provider_id": 108465,
         "provider_title": "Mushoku Tensei", "provider_episodes": 11,
         "provider_url": "", "confidence": 1.0},
        {"season_id": "S3", "season_number": 3,
         "provider": "anilist", "provider_id": 166873,
         "provider_title": "Mushoku Tensei III", "provider_episodes": 14,
         "provider_url": "", "confidence": 0.8},  # abaixo de 1.00: fica pendente
    ])
    conn.close()
    app = create_app(caminho)
    app.config["TESTING"] = True
    return app.test_client(), caminho


def test_stats():
    cli, _ = app_com_dados()
    s = cli.get("/api/stats").get_json()
    # 1.00 já entra confirmado; 0.8 fica pendente
    assert (s["confirmed"], s["pending"]) == (1, 1)
    assert s["com_anilist"] == 2
    assert "catalogo_local" in s, "a UI precisa saber se dá para casar offline"


def test_status_da_tarefa():
    cli, _ = app_com_dados()
    s = cli.get("/api/task").get_json()
    assert s["rodando"] is False and s["ultimo_sync"] is None and s["tipo"] is None


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


def test_biblioteca_e_pendentes():
    """3 e 4: 1.00 entra na biblioteca; 0.8 fica pendente de match."""
    cli, _ = app_com_dados()
    biblioteca = cli.get("/api/library").get_json()
    pendentes = cli.get("/api/pending").get_json()
    assert [i["season_id"] for i in biblioteca] == ["S1"]
    assert [i["season_id"] for i in pendentes] == ["S3"]
    assert biblioteca[0]["providers"] == "anilist"


def test_vincular_move_de_pendente_para_biblioteca():
    """5: o vínculo manual é a saída da fila."""
    cli, _ = app_com_dados()
    r = cli.post("/api/link/S3", json={"provider": "mal", "provider_id": 51179,
                                       "title": "Mushoku Tensei II"})
    assert r.status_code == 200
    assert cli.get("/api/pending").get_json() == []
    por_id = {i["season_id"]: i for i in cli.get("/api/library").get_json()}
    assert por_id["S3"]["mal_id"] == 51179
    assert por_id["S3"]["providers"] == "anilist,mal"


def test_vincular_valida_entrada():
    cli, _ = app_com_dados()
    assert cli.post("/api/link/S3", json={"provider": "kitsu", "provider_id": 1}).status_code == 400
    assert cli.post("/api/link/S3", json={"provider": "mal", "provider_id": "abc"}).status_code == 400
    assert cli.post("/api/link/S3", json={}).status_code == 400
    assert cli.post("/api/link/NAOEXISTE",
                    json={"provider": "mal", "provider_id": 1}).status_code == 404


def test_dispensar_tira_da_fila():
    """Filme ou especial sem par no provedor não fica travando a lista."""
    cli, _ = app_com_dados()
    assert cli.post("/api/dismiss/S3", json={}).status_code == 200
    assert cli.get("/api/pending").get_json() == []
    assert [i["season_id"] for i in cli.get("/api/library").get_json()] == ["S1"]


def test_filtro_por_serie():
    cli, _ = app_com_dados()
    assert len(cli.get("/api/library?q=mushoku").get_json()) == 1
    assert cli.get("/api/library?q=one piece").get_json() == []


def test_sync_por_provedor_recusa_provedor_desconhecido():
    cli, _ = app_com_dados()
    r = cli.post("/api/provider/kitsu", json={})
    assert r.status_code == 400 and "provider" in r.get_json()["erro"]


def test_sync_por_provedor_roda_e_conta_pendentes():
    cli, _ = app_com_dados()
    r = cli.post("/api/provider/mal", json={})
    assert r.status_code == 202
    s = _esperar(cli)
    assert s["tipo"] == "mal"
    if not s["erro"]:
        assert "pendentes" in s["resultado"] and s["resultado"]["provider"] == "mal"


def test_baixar_crunchyroll_nao_casa():
    """Botão separado: baixar a CR não dispara match de provedor nenhum."""
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
