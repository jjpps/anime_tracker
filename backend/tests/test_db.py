"""Checagem da persistência. Sem rede.

    python tests/test_db.py
"""

import os
import sqlite3
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db  # noqa: E402

SERIE = {"series_id": "G1", "series_title": "Mushoku Tensei", "availability": "available",
         "total_episodes": 60, "total_seasons": 3}


def ep(n, quando="2026-01-01T00:00:00Z"):
    return {"episode_number": float(n), "released_at": quando}


SEASONS = [
    {"season_id": "S1", "season_number": 1, "season_title": "Season 1",
     "total_episodes": 2, "episodes": [ep(1), ep(2)]},
    {"season_id": "S3", "season_number": 3, "season_title": "Season 3",
     "total_episodes": 1, "episodes": [ep(1)]},
]


def novo_banco():
    conn = db.connect(":memory:")
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, SERIE["series_id"], SEASONS)
    return conn


# --- caminho do banco ---

def test_caminho_do_banco_ancora_na_raiz():
    """Rodar de outro diretório não pode criar um banco novo e vazio."""
    from anime_tracker.config import RAIZ

    anterior = os.environ.pop("ANIME_TRACKER_DB", None)
    try:
        os.environ["ANIME_TRACKER_DB"] = "anime_tracker.db"
        assert db.resolve_path() == os.path.join(RAIZ, "anime_tracker.db")
        assert db.resolve_path("/tmp/x.db") == "/tmp/x.db"
        assert db.resolve_path(":memory:") == ":memory:"
        # caminho com separador é do cwd: ancorar na raiz criaria banco perdido
        assert db.resolve_path("../x.db") == "../x.db"
        assert db.resolve_path("dados/x.db") == "dados/x.db"
    finally:
        os.environ.pop("ANIME_TRACKER_DB", None)
        if anterior is not None:
            os.environ["ANIME_TRACKER_DB"] = anterior


# --- gravação ---

def test_grava_series_temporadas_e_episodios():
    conn = novo_banco()
    s = db.stats(conn)
    assert (s["series"], s["seasons"]) == (1, 2)
    assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 3


def test_importar_de_novo_e_idempotente():
    conn = novo_banco()
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, SERIE["series_id"], SEASONS)
    assert db.stats(conn)["seasons"] == 2
    assert conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0] == 3


def test_episodios_sao_trocados_pelos_novos():
    """A CR pode renumerar ou tirar episódio: o que vale é a última leitura."""
    conn = novo_banco()
    db.save_seasons(conn, "G1", [{**SEASONS[0], "episodes": [ep(1)]}])
    linhas = conn.execute("SELECT episode_number FROM episodes WHERE season_id='S1'").fetchall()
    assert [r[0] for r in linhas] == [1.0]


def test_temporada_sem_id_e_ignorada():
    conn = novo_banco()
    db.save_seasons(conn, "G1", [{**SEASONS[0], "season_id": ""}])
    assert db.stats(conn)["seasons"] == 2


def test_banco_antigo_abre_e_perde_o_match():
    """Banco de antes do ADR 0001: colunas extras continuam, a tabela de match sai."""
    caminho = tempfile.mktemp(suffix=".db")
    velho = sqlite3.connect(caminho)
    velho.executescript("""
        CREATE TABLE series (series_id TEXT PRIMARY KEY, title TEXT NOT NULL,
            availability TEXT, total_episodes INTEGER, total_seasons INTEGER,
            added_at TEXT, is_favorite INTEGER NOT NULL DEFAULT 0,
            in_watchlist INTEGER NOT NULL DEFAULT 1, synced_at TEXT NOT NULL);
        CREATE TABLE seasons (season_id TEXT PRIMARY KEY, series_id TEXT NOT NULL,
            season_number INTEGER NOT NULL, title TEXT,
            total_episodes INTEGER NOT NULL DEFAULT 0, year_start INTEGER, year_end INTEGER);
        CREATE TABLE matches (season_id TEXT PRIMARY KEY);
    """)
    velho.close()

    conn = db.connect(caminho)
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, "G1", SEASONS)
    tabelas = {r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    assert "matches" not in tabelas and "episodes" in tabelas
    assert db.stats(conn)["seasons"] == 2


def test_setting_vazio_volta_none():
    conn = db.connect(":memory:")
    db.set_setting(conn, "x", "a")
    db.set_setting(conn, "x", None)
    assert db.get_setting(conn, "x") is None


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
