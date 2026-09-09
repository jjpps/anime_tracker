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


def match_ok(resultado):
    """Match automático só com certeza total.

    Confiança 1.00 é título idêntico com episódios e ano batendo — não sobra
    dúvida a resolver. Qualquer valor abaixo vai para pendentes.

    Duplicata fica de fora mesmo em 1.00: duas temporadas apontando para a
    mesma obra é justamente o caso ambíguo, por mais parecidos que sejam os
    títulos."""
    return (
        resultado.get("provider_id") is not None
        and resultado.get("confidence", 0) >= 1.0
        and resultado.get("duplicate_of") is None
    )


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
            "review_status": "confirmed" if match_ok(r) else "pending",
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
               {colunas_status} confidence, duplicate_of, review_status, matched_at)
            VALUES (:season_id, :ident, :titulo, :episodios, {valores_url}
                    {valores_status} :confidence, :duplicate_of, :review_status,
                    :matched_at)
            ON CONFLICT(season_id) DO UPDATE SET
              {p}_id=excluded.{p}_id, {p}_title=excluded.{p}_title,
              {p}_episodes=excluded.{p}_episodes, {extra_url} {extra_status}
              confidence=excluded.confidence,
              duplicate_of=excluded.duplicate_of, matched_at=excluded.matched_at,
              -- confirmado não regride: o segundo provedor acrescenta, não rebaixa
              review_status=CASE WHEN matches.review_status = 'confirmed'
                                 THEN 'confirmed' ELSE excluded.review_status END
            -- o guard protege vínculo EXISTENTE, não impede vínculo NOVO: sem a
            -- segunda condição, casar no AniList com 1.00 travaria a linha e o
            -- MyAnimeList nunca conseguiria gravar o id dele
            WHERE matches.review_status = 'pending' OR matches.{p}_id IS NULL""",
        valores,
    )
    conn.commit()
    return len(valores)





def seasons_of(conn, series_id):
    """Temporadas de uma série, na ordem — entrada do matcher."""
    return conn.execute(
        "SELECT * FROM seasons WHERE series_id = ? ORDER BY season_number", [series_id]
    ).fetchall()


# --- leitura: as duas telas ---

_COLUNAS = """m.season_id, m.anilist_id, m.anilist_title, m.anilist_url,
              m.mal_id, m.mal_title, m.confidence, m.duplicate_of,
              m.review_status, s.season_number, s.title AS season_title,
              s.total_episodes AS cr_episodes, se.series_id, se.title AS series_title,
              CASE WHEN m.anilist_id IS NOT NULL AND m.mal_id IS NOT NULL
                     THEN 'anilist,mal'
                   WHEN m.anilist_id IS NOT NULL THEN 'anilist'
                   WHEN m.mal_id IS NOT NULL THEN 'mal'
                   ELSE '' END AS providers"""
_JOIN = """FROM matches m
           JOIN seasons s USING (season_id)
           JOIN series se USING (series_id)"""


def biblioteca(conn):
    """Feature 3: os matches já resolvidos, automáticos ou confirmados na mão."""
    return conn.execute(
        f"""SELECT {_COLUNAS} {_JOIN}
             WHERE m.review_status = 'confirmed'
               AND (m.anilist_id IS NOT NULL OR m.mal_id IS NOT NULL)
             ORDER BY se.title, s.season_number"""
    ).fetchall()


def pendentes(conn):
    """Feature 4: o que não fechou em 1.00 e precisa de decisão.

    Sem filtro por provedor de propósito: um match de confiança 0.8 TEM o id do
    provedor, e filtrar por "id ausente" esconderia exatamente o que precisa de
    correção. Pendente é pendente."""
    return conn.execute(
        f"""SELECT {_COLUNAS} {_JOIN}
             WHERE m.review_status = 'pending'
             ORDER BY m.confidence DESC, se.title, s.season_number"""
    ).fetchall()


def vincular(conn, season_id, provider, provider_id, titulo=None):
    """Feature 5: liga a temporada a um id do provedor, na mão.

    Vínculo manual entra como confirmado: quem digitou o id já decidiu."""
    if provider not in PROVIDERS:
        raise ValueError(f"provider inválido: {provider}")
    cur = conn.execute(
        f"""UPDATE matches
               SET {provider}_id = ?, {provider}_title = COALESCE(?, {provider}_title),
                   review_status = 'confirmed', reviewed_at = ?
             WHERE season_id = ?""",
        [int(provider_id), titulo, agora(), season_id],
    )
    conn.commit()
    return cur.rowcount


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




def stats(conn):
    linha = conn.execute(
        """SELECT
             (SELECT COUNT(*) FROM series)                                        AS series,
             (SELECT COUNT(*) FROM seasons)                                       AS seasons,
             (SELECT COUNT(*) FROM watch_history)                                 AS episodes,
             (SELECT COUNT(*) FROM matches
               WHERE anilist_id IS NOT NULL OR mal_id IS NOT NULL)              AS matched,
             (SELECT COUNT(*) FROM matches WHERE review_status = 'pending')       AS pending,
             (SELECT COUNT(*) FROM matches WHERE review_status = 'confirmed')     AS confirmed,
             (SELECT COUNT(*) FROM matches WHERE review_status = 'rejected')      AS rejected,
             (SELECT COUNT(*) FROM matches WHERE anilist_id IS NOT NULL)         AS com_anilist,
             (SELECT COUNT(*) FROM matches WHERE mal_id IS NOT NULL)             AS com_mal"""
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


