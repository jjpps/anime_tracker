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
    mal_id           INTEGER,
    mal_title        TEXT,
    mal_episodes     INTEGER,
    mal_status       TEXT,
    mal_checked_at   TEXT,
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

-- menu 1: tudo que já tem correspondência no AniList, revisado ou não
CREATE VIEW IF NOT EXISTS v_catalog AS
SELECT m.*, s.series_id, s.season_number, s.title AS season_title,
       s.total_episodes AS cr_episodes, se.title AS series_title
FROM matches m
JOIN seasons s USING (season_id)
JOIN series se USING (series_id)
WHERE m.anilist_id IS NOT NULL
ORDER BY se.title, s.season_number;

-- menu 2: o que ainda precisa de decisão
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
    ("matches", "mal_id", "INTEGER"),
    ("matches", "mal_title", "TEXT"),
    ("matches", "mal_episodes", "INTEGER"),
    ("matches", "mal_status", "TEXT"),
    ("matches", "mal_checked_at", "TEXT"),
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


PROVIDERS = ("anilist", "mal")


def save_matches(conn, resultados, provider=None):
    """Grava matches SEM tocar no que já foi revisado.

    O WHERE no ON CONFLICT é o ponto todo: rodar o matcher de novo não pode
    desfazer uma decisão humana.

    O resultado do matcher é neutro (`provider_*`); aqui ele vira coluna do
    provedor escolhido. Um match no AniList não apaga o vínculo com o MAL e
    vice-versa: uma temporada pode estar ligada aos dois."""
    linhas = [r for r in resultados if r.get("season_id")]
    if not linhas:
        return 0

    provider = provider or linhas[0].get("provider") or "anilist"
    if provider not in PROVIDERS:
        raise ValueError(f"provider inválido: {provider}")
    # nomes vêm de uma lista fechada, então a interpolação é segura
    p = provider

    valores = [
        {
            "season_id": r["season_id"],
            "ident": r.get("provider_id"),
            "titulo": r.get("provider_title"),
            "episodios": r.get("provider_episodes"),
            "url": r.get("provider_url"),
            "status": r.get("provider_status"),
            "confidence": r["confidence"],
            "duplicate_of": r.get("duplicate_of"),
            "matched_at": agora(),
        }
        for r in linhas
    ]
    extra_url = f"{p}_url=excluded.{p}_url," if p == "anilist" else ""
    colunas_url = f"{p}_url," if p == "anilist" else ""
    valores_url = ":url," if p == "anilist" else ""
    extra_status = f"{p}_status=excluded.{p}_status," if p == "mal" else ""
    colunas_status = f"{p}_status," if p == "mal" else ""
    valores_status = ":status," if p == "mal" else ""

    conn.executemany(
        f"""INSERT INTO matches
              (season_id, {p}_id, {p}_title, {p}_episodes, {colunas_url}
               {colunas_status} confidence, duplicate_of, matched_at)
            VALUES (:season_id, :ident, :titulo, :episodios, {valores_url}
                    {valores_status} :confidence, :duplicate_of, :matched_at)
            ON CONFLICT(season_id) DO UPDATE SET
              {p}_id=excluded.{p}_id, {p}_title=excluded.{p}_title,
              {p}_episodes=excluded.{p}_episodes, {extra_url} {extra_status}
              confidence=excluded.confidence,
              duplicate_of=excluded.duplicate_of, matched_at=excluded.matched_at
            WHERE matches.review_status = 'pending'""",
        valores,
    )
    conn.commit()
    return len(valores)


def set_mal_ids(conn, pares):
    """Grava mal_id e status da obra. `pares`: [(season_id, mal_id, status)]."""
    conn.executemany("UPDATE matches SET mal_id = ?, mal_status = ? WHERE season_id = ?",
                     [(mal_id, status, season_id) for season_id, mal_id, status in pares])
    conn.commit()
    return len(pares)


def set_mal_check(conn, season_id, titulo, episodios):
    """Registra o que a API do MAL respondeu para esse id."""
    conn.execute(
        "UPDATE matches SET mal_title = ?, mal_episodes = ?, mal_checked_at = ? "
        "WHERE season_id = ?",
        [titulo, episodios, agora(), season_id],
    )
    conn.commit()


def matches_para_exportar(conn):
    """Tudo que tem mal_id e não foi rejeitado, com o contexto da temporada."""
    return conn.execute(
        """SELECT m.season_id, m.mal_id, m.mal_title, m.mal_episodes, m.mal_status,
                  m.anilist_id, m.anilist_title, m.anilist_episodes,
                  m.review_status, m.confidence,
                  s.series_id, s.season_number, s.total_episodes AS cr_episodes,
                  se.title AS series_title
             FROM matches m
             JOIN seasons s USING (season_id)
             JOIN series se USING (series_id)
            WHERE m.mal_id IS NOT NULL AND m.review_status != 'rejected'
            ORDER BY se.title, s.season_number"""
    ).fetchall()


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

def catalog(conn, limit=None):
    """Menu 1: temporadas com match resolvido, independente da revisão."""
    sql = "SELECT * FROM v_catalog"
    return conn.execute(sql + (f" LIMIT {int(limit)}" if limit else "")).fetchall()


def biblioteca(conn):
    """Tudo que já tem vínculo com algum provedor, com o rótulo de qual.

    Uma temporada pode estar ligada aos dois; `providers` diz quais."""
    return conn.execute(
        """SELECT m.season_id, s.season_number, s.title AS season_title,
                  s.total_episodes AS cr_episodes, se.title AS series_title,
                  se.series_id, m.anilist_id, m.anilist_title, m.anilist_url,
                  m.mal_id, m.mal_title, m.confidence, m.review_status,
                  CASE WHEN m.anilist_id IS NOT NULL AND m.mal_id IS NOT NULL
                         THEN 'anilist,mal'
                       WHEN m.anilist_id IS NOT NULL THEN 'anilist'
                       ELSE 'mal' END AS providers
             FROM matches m
             JOIN seasons s USING (season_id)
             JOIN series se USING (series_id)
            WHERE m.anilist_id IS NOT NULL OR m.mal_id IS NOT NULL
            ORDER BY se.title, s.season_number"""
    ).fetchall()


def precisam_correcao(conn, provider=None):
    """O que o sync não conseguiu resolver com confiança.

    Três motivos, todos exigindo olho humano: nenhuma correspondência,
    confiança baixa, ou duas temporadas apontando para a mesma obra."""
    filtro = ""
    if provider:
        if provider not in PROVIDERS:
            raise ValueError(f"provider inválido: {provider}")
        filtro = f" AND (m.{provider}_id IS NULL OR m.confidence < 0.9 OR m.duplicate_of IS NOT NULL)"
    else:
        filtro = (" AND ((m.anilist_id IS NULL AND m.mal_id IS NULL)"
                  " OR m.confidence < 0.9 OR m.duplicate_of IS NOT NULL)")
    return conn.execute(
        f"""SELECT m.*, s.season_number, s.title AS season_title,
                   s.total_episodes AS cr_episodes, se.title AS series_title,
                   se.series_id
              FROM matches m
              JOIN seasons s USING (season_id)
              JOIN series se USING (series_id)
             WHERE m.review_status = 'pending'{filtro}
             ORDER BY m.confidence ASC, se.title"""
    ).fetchall()


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
             (SELECT COUNT(*) FROM matches WHERE review_status = 'rejected')      AS rejected,
             (SELECT COUNT(*) FROM matches WHERE mal_id IS NOT NULL)             AS com_mal_id,
             (SELECT COUNT(*) FROM matches WHERE mal_checked_at IS NOT NULL)     AS mal_conferidos"""
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
