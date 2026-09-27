"""Persistência em SQLite. Sem ORM: sqlite3 é stdlib e o schema tem 5 tabelas."""

import os
import sqlite3
from datetime import datetime, timezone

from .config import RAIZ

DB_PADRAO = "anime_tracker.db"


def resolve_path(path=None):
    """Caminho do banco.

    Nome solto ("anime_tracker.db") ancora na raiz do projeto: relativo ao cwd
    criaria um banco por diretório de onde se roda — `sync` na raiz e `serve`
    em backend/ dariam bancos diferentes e tela vazia, sem erro.

    Caminho com separador ("../x.db", "dados/x.db") é respeitado como escrito;
    quem digita um caminho está dizendo onde quer, e ancorar isso na raiz
    produz um banco vazio em lugar inesperado."""
    caminho = path or os.environ.get("ANIME_TRACKER_DB") or DB_PADRAO
    if caminho == ":memory:" or os.path.isabs(caminho) or os.sep in caminho:
        return caminho
    return os.path.join(RAIZ, caminho)


SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    series_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    availability    TEXT,
    total_episodes  INTEGER,
    total_seasons   INTEGER,
    synced_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seasons (
    season_id       TEXT PRIMARY KEY,
    series_id       TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    season_number   INTEGER NOT NULL,
    title           TEXT,
    total_episodes  INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_seasons_series ON seasons(series_id);

-- só o que a continuação precisa: número e quando chegou na CR
CREATE TABLE IF NOT EXISTS episodes (
    season_id       TEXT NOT NULL REFERENCES seasons(season_id) ON DELETE CASCADE,
    episode_number  REAL NOT NULL,
    released_at     TEXT,
    PRIMARY KEY (season_id, episode_number)
);

CREATE TABLE IF NOT EXISTS watch_history (
    episode_id      TEXT PRIMARY KEY,
    series_id       TEXT NOT NULL,
    series_title    TEXT,
    season_number   INTEGER,
    episode_number  REAL,
    episode_title   TEXT,
    watched_at      TEXT,
    fully_watched   INTEGER NOT NULL DEFAULT 0
);
CREATE INDEX IF NOT EXISTS idx_history_series ON watch_history(series_id, season_number);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT,
    saved_at TEXT NOT NULL
);

-- o match com AniList/MAL saiu (docs/adr/0001)
DROP TABLE IF EXISTS matches;
"""


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# colunas acrescentadas depois: CREATE TABLE IF NOT EXISTS não altera tabela
# existente, então banco antigo precisa do ALTER
COLUNAS_NOVAS = [
    ("watch_history", "series_title", "TEXT"),
]


def migrar(conn):
    for tabela, coluna, tipo in COLUNAS_NOVAS:
        existentes = {r["name"] for r in conn.execute(f"PRAGMA table_info({tabela})")}
        if existentes and coluna not in existentes:
            conn.execute(f"ALTER TABLE {tabela} ADD COLUMN {coluna} {tipo}")
    conn.commit()


def connect(path=None):
    # resolvido na chamada, não no import: o .env é carregado depois dos imports
    conn = sqlite3.connect(resolve_path(path))
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    conn.executescript(SCHEMA)
    migrar(conn)
    return conn


# --- escrita ---

def save_series(conn, series):
    conn.executemany(
        """INSERT INTO series
             (series_id, title, availability, total_episodes, total_seasons, synced_at)
           VALUES (:series_id, :series_title, :availability, :total_episodes,
                   :total_seasons, :synced_at)
           ON CONFLICT(series_id) DO UPDATE SET
             title=excluded.title, availability=excluded.availability,
             total_episodes=excluded.total_episodes,
             total_seasons=excluded.total_seasons, synced_at=excluded.synced_at""",
        [{**s, "synced_at": agora()} for s in series],
    )
    conn.commit()


def save_seasons(conn, series_id, seasons):
    """Grava as temporadas e troca os episódios de cada uma pelos que vieram."""
    seasons = [s for s in seasons if s.get("season_id")]
    conn.executemany(
        """INSERT INTO seasons
             (season_id, series_id, season_number, title, total_episodes)
           VALUES (:season_id, :series_id, :season_number, :season_title, :total_episodes)
           ON CONFLICT(season_id) DO UPDATE SET
             season_number=excluded.season_number, title=excluded.title,
             total_episodes=excluded.total_episodes""",
        [{**s, "series_id": series_id} for s in seasons],
    )
    conn.executemany("DELETE FROM episodes WHERE season_id = ?",
                     [[s["season_id"]] for s in seasons])
    conn.executemany(
        """INSERT OR REPLACE INTO episodes (season_id, episode_number, released_at)
           VALUES (?, ?, ?)""",
        [[s["season_id"], e["episode_number"], e["released_at"]]
         for s in seasons for e in s.get("episodes", [])],
    )
    conn.commit()


def save_history(conn, episodes):
    """Histórico é append-only do lado da CR; conflito só reescreve o progresso."""
    conn.executemany(
        """INSERT INTO watch_history
             (episode_id, series_id, series_title, season_number, episode_number,
              episode_title, watched_at, fully_watched)
           VALUES (:episode_id, :series_id, :series_title, :season_number,
                   :episode_number, :episode_title, :watched_at, :fully_watched)
           ON CONFLICT(episode_id) DO UPDATE SET
             series_title=excluded.series_title,
             watched_at=excluded.watched_at,
             fully_watched=excluded.fully_watched""",
        [{**e, "fully_watched": int(e["fully_watched"])} for e in episodes],
    )
    conn.commit()


def stats(conn):
    return dict(conn.execute(
        """SELECT (SELECT COUNT(*) FROM series)        AS series,
                  (SELECT COUNT(*) FROM seasons)       AS seasons,
                  (SELECT COUNT(*) FROM watch_history) AS episodes"""
    ).fetchone())


def get_setting(conn, key, default=None):
    linha = conn.execute("SELECT value FROM settings WHERE key = ?", [key]).fetchone()
    return linha["value"] if linha else default


def set_setting(conn, key, value):
    conn.execute(
        """INSERT INTO settings (key, value, saved_at) VALUES (?, ?, ?)
           ON CONFLICT(key) DO UPDATE SET value=excluded.value, saved_at=excluded.saved_at""",
        [key, value, agora()],
    )
    conn.commit()


