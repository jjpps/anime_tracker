"""Persistência em SQLite. Sem ORM: sqlite3 é stdlib e o schema tem 4 tabelas.

Regra central: o matcher roda quantas vezes for preciso, mas nunca sobrescreve
um match que uma pessoa já revisou.
"""

import os
import sqlite3
from datetime import datetime, timezone

from .config import RAIZ

DB_PADRAO = "anime_tracker.db"


def resolve_path(path=None):
    """Caminho do banco, sempre ancorado na raiz do projeto.

    Relativo ao cwd criaria um banco por diretório de onde se roda: `sync` na
    raiz e `serve` em backend/ dariam bancos diferentes e tela vazia."""
    caminho = path or os.environ.get("ANIME_TRACKER_DB") or DB_PADRAO
    if caminho == ":memory:" or os.path.isabs(caminho):
        return caminho
    return os.path.join(RAIZ, caminho)

SCHEMA = """
CREATE TABLE IF NOT EXISTS series (
    series_id       TEXT PRIMARY KEY,
    title           TEXT NOT NULL,
    availability    TEXT,
    total_episodes  INTEGER,
    total_seasons   INTEGER,
    added_at        TEXT,
    is_favorite     INTEGER NOT NULL DEFAULT 0,
    in_watchlist    INTEGER NOT NULL DEFAULT 1,
    synced_at       TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS seasons (
    season_id       TEXT PRIMARY KEY,
    series_id       TEXT NOT NULL REFERENCES series(series_id) ON DELETE CASCADE,
    season_number   INTEGER NOT NULL,
    title           TEXT,
    total_episodes  INTEGER NOT NULL DEFAULT 0,
    year_start      INTEGER,
    year_end        INTEGER
);
CREATE INDEX IF NOT EXISTS idx_seasons_series ON seasons(series_id);

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

CREATE TABLE IF NOT EXISTS matches (
    season_id        TEXT PRIMARY KEY REFERENCES seasons(season_id) ON DELETE CASCADE,
    anilist_id       INTEGER,
    anilist_title    TEXT,
    anilist_episodes INTEGER,
    anilist_url      TEXT,
    confidence       REAL NOT NULL DEFAULT 0,
    duplicate_of     INTEGER,
    review_status    TEXT NOT NULL DEFAULT 'pending'
                     CHECK (review_status IN ('pending', 'confirmed', 'rejected')),
    reviewed_at      TEXT,
    matched_at       TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_matches_status ON matches(review_status);

CREATE TABLE IF NOT EXISTS settings (
    key    TEXT PRIMARY KEY,
    value  TEXT,
    saved_at TEXT NOT NULL
);

-- as duas faces do que o usuário pediu separar
CREATE VIEW IF NOT EXISTS v_pending_review AS
SELECT m.*, s.series_id, s.season_number, s.title AS season_title,
       s.total_episodes AS cr_episodes, se.title AS series_title
FROM matches m
JOIN seasons s USING (season_id)
JOIN series se USING (series_id)
WHERE m.review_status = 'pending'
ORDER BY m.confidence ASC;

CREATE VIEW IF NOT EXISTS v_reviewed AS
SELECT m.*, s.series_id, s.season_number, s.title AS season_title,
       s.total_episodes AS cr_episodes, se.title AS series_title
FROM matches m
JOIN seasons s USING (season_id)
JOIN series se USING (series_id)
WHERE m.review_status IN ('confirmed', 'rejected')
ORDER BY m.reviewed_at DESC;
"""


def agora():
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


# colunas acrescentadas depois: CREATE TABLE IF NOT EXISTS não altera tabela
# existente, então banco antigo precisa do ALTER
COLUNAS_NOVAS = [
    ("series", "in_watchlist", "INTEGER NOT NULL DEFAULT 1"),
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
             (series_id, title, availability, total_episodes, total_seasons,
              added_at, is_favorite, in_watchlist, synced_at)
           VALUES (:series_id, :series_title, :availability, :total_episodes,
                   :total_seasons, :added_at, :is_favorite, :in_watchlist, :synced_at)
           ON CONFLICT(series_id) DO UPDATE SET
             title=excluded.title, availability=excluded.availability,
             total_episodes=excluded.total_episodes,
             total_seasons=excluded.total_seasons,
             is_favorite=excluded.is_favorite,
             in_watchlist=excluded.in_watchlist, synced_at=excluded.synced_at""",
        [
            {
                "in_watchlist": True,  # sobreposto se a série trouxer o campo
                **s,
                "is_favorite": int(s["is_favorite"]),
                "synced_at": agora(),
            }
            for s in series
        ],
    )
    conn.commit()


def save_seasons(conn, series_id, seasons):
    conn.executemany(
        """INSERT INTO seasons
             (season_id, series_id, season_number, title, total_episodes,
              year_start, year_end)
           VALUES (:season_id, :series_id, :season_number, :season_title,
                   :total_episodes, :year_start, :year_end)
           ON CONFLICT(season_id) DO UPDATE SET
             season_number=excluded.season_number, title=excluded.title,
             total_episodes=excluded.total_episodes,
             year_start=excluded.year_start, year_end=excluded.year_end""",
        [
            {
                **s,
                "series_id": series_id,
                "year_start": (s.get("years") or (None, None))[0],
                "year_end": (s.get("years") or (None, None))[1],
            }
            for s in seasons
        ],
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


def save_matches(conn, resultados):
    """Grava matches SEM tocar no que já foi revisado.

    O WHERE no ON CONFLICT é o ponto todo: rodar o matcher de novo não pode
    desfazer uma decisão humana."""
    linhas = []
    for r in resultados:
        if not r.get("season_id"):
            continue
        linhas.append({
            "season_id": r["season_id"],
            "anilist_id": r["anilist_id"],
            "anilist_title": r["anilist_title"],
            "anilist_episodes": r["anilist_episodes"],
            "anilist_url": r["anilist_url"],
            "confidence": r["confidence"],
            "duplicate_of": r.get("duplicate_of"),
            "matched_at": agora(),
        })
    conn.executemany(
        """INSERT INTO matches
             (season_id, anilist_id, anilist_title, anilist_episodes, anilist_url,
              confidence, duplicate_of, matched_at)
           VALUES (:season_id, :anilist_id, :anilist_title, :anilist_episodes,
                   :anilist_url, :confidence, :duplicate_of, :matched_at)
           ON CONFLICT(season_id) DO UPDATE SET
             anilist_id=excluded.anilist_id, anilist_title=excluded.anilist_title,
             anilist_episodes=excluded.anilist_episodes,
             anilist_url=excluded.anilist_url, confidence=excluded.confidence,
             duplicate_of=excluded.duplicate_of, matched_at=excluded.matched_at
           WHERE matches.review_status = 'pending'""",
        linhas,
    )
    conn.commit()
    return len(linhas)


def set_review(conn, season_id, status, anilist_id=None):
    """Marca um match como revisado. anilist_id permite corrigir o alvo na mão."""
    if status not in ("pending", "confirmed", "rejected"):
        raise ValueError(f"status inválido: {status}")
    campos = "review_status = ?, reviewed_at = ?"
    params = [status, agora() if status != "pending" else None]
    if anilist_id is not None:
        campos += ", anilist_id = ?"
        params.append(anilist_id)
    cur = conn.execute(f"UPDATE matches SET {campos} WHERE season_id = ?", [*params, season_id])
    conn.commit()
    return cur.rowcount


# --- leitura ---

def pending_review(conn, limit=None):
    sql = "SELECT * FROM v_pending_review"
    return conn.execute(sql + (f" LIMIT {int(limit)}" if limit else "")).fetchall()


def reviewed(conn, limit=None):
    sql = "SELECT * FROM v_reviewed"
    return conn.execute(sql + (f" LIMIT {int(limit)}" if limit else "")).fetchall()


def stats(conn):
    linha = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM series)                                        AS series,
             (SELECT COUNT(*) FROM seasons)                                       AS seasons,
             (SELECT COUNT(*) FROM watch_history)                                 AS episodes,
             (SELECT COUNT(*) FROM matches WHERE anilist_id IS NOT NULL)          AS matched,
             (SELECT COUNT(*) FROM matches WHERE review_status = 'pending')       AS pending,
             (SELECT COUNT(*) FROM matches WHERE review_status = 'confirmed')     AS confirmed,
             (SELECT COUNT(*) FROM matches WHERE review_status = 'rejected')      AS rejected"""
    ).fetchone()
    return dict(linha)


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


def seasons_of(conn, series_id):
    return conn.execute(
        "SELECT * FROM seasons WHERE series_id = ? ORDER BY season_number", [series_id]
    ).fetchall()
