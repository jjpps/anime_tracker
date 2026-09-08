"""Regra do sync incremental.

O gargalo não é o histórico, são as temporadas: listar as temporadas de uma
série é 1 chamada, mas a faixa de anos exige 1 chamada por temporada — ~170 no
total. Então a regra é detectar barato o que mudou e só aí pagar o caro.

Camadas:
  1. histórico incremental, parando na marca d'água do último sync;
  2. escopo = watchlist ∪ séries distintas do histórico, resolvidas em lote
     (3 chamadas para 110 séries) — traz episode_count/season_count;
  3. temporadas rebuscadas só para série cuja contagem mudou ou que nunca foi
     sincronizada;
  4. match das temporadas sem correspondência, que é o que alimenta a fila de
     revisão — sincronizar sem casar deixaria as duas telas vazias.

`is_complete` da temporada NÃO serve como sinal: a CR devolve False até para
temporada encerrada há anos.
"""

import logging
from datetime import datetime, timedelta, timezone

from . import db
from .anilist import match_seasons

log = logging.getLogger("anime_tracker.sync")

TTL_HORAS = 6
# uma folga na marca d'água custa uma página e cobre desordem na borda
OVERLAP = timedelta(days=1)
ULTIMO_SYNC = "last_sync_at"


# distingue "descubra a fonte sozinho" de "não case nada": com um único None
# os dois sentidos se confundem e o teste acaba batendo na rede
AUTO = object()


class SyncBloqueado(Exception):
    """Sync pedido antes do TTL. Carrega quantos minutos faltam."""

    def __init__(self, minutos):
        super().__init__(f"sincronizado há pouco; tente em {minutos} min")
        self.minutos_restantes = minutos


def minutos_ate_liberar(conn, ttl_horas=TTL_HORAS):
    ultimo = db.get_setting(conn, ULTIMO_SYNC)
    if not ultimo:
        return 0
    try:
        quando = datetime.fromisoformat(ultimo)
    except ValueError:
        return 0
    falta = (quando + timedelta(hours=ttl_horas)) - datetime.now(timezone.utc)
    return max(0, int(falta.total_seconds() // 60))


def marca_dagua(conn):
    """Data do episódio mais recente já gravado, menos a folga."""
    linha = conn.execute("SELECT MAX(watched_at) AS m FROM watch_history").fetchone()
    if not linha or not linha["m"]:
        return None
    try:
        quando = datetime.fromisoformat(linha["m"].replace("Z", "+00:00"))
    except ValueError:
        return None
    return (quando - OVERLAP).isoformat().replace("+00:00", "Z")


def precisa_temporadas(serie_nova, guardada):
    """Rebuscar temporadas? Só se nunca sincronizou ou se a contagem mudou.

    episode_count sobe quando estreia episódio novo, então a detecção pega
    temporada nova e episódio semanal sem custo extra."""
    if guardada is None or not guardada["tem_temporadas"]:
        return True
    return (
        serie_nova["total_episodes"] != guardada["total_episodes"]
        or serie_nova["total_seasons"] != guardada["total_seasons"]
    )


def estado_guardado(conn):
    """series_id -> contagens gravadas e se já tem temporadas."""
    linhas = conn.execute(
        """SELECT s.series_id, s.total_episodes, s.total_seasons,
                  EXISTS(SELECT 1 FROM seasons t WHERE t.series_id = s.series_id) AS tem_temporadas
             FROM series s"""
    ).fetchall()
    return {r["series_id"]: dict(r) for r in linhas}


def escopo(conn, ids_watchlist):
    """Watchlist ∪ séries distintas do histórico."""
    do_historico = {
        r["series_id"]
        for r in conn.execute("SELECT DISTINCT series_id FROM watch_history WHERE series_id != ''")
    }
    return list(dict.fromkeys([*ids_watchlist, *do_historico]))


def cliente_de_match():
    """(cliente, nome da fonte). AniList se estiver no ar; senão o catálogo local.

    A troca de fonte é reportada em vez de silenciosa: casar contra outra base
    sem dizer seria esconder de onde veio o dado."""
    from .anilist import AniList
    from .catalog import CatalogoAusente, OfflineIndex

    log.info("escolhendo fonte de match: sondando o AniList")
    cliente = AniList()
    if cliente.disponivel():
        log.info("fonte de match: API do AniList")
        return cliente, "anilist"
    try:
        indice = OfflineIndex()
        log.info("fonte de match: catálogo local (AniList fora do ar)")
        return indice, "catálogo local"
    except CatalogoAusente as e:
        log.error("sem fonte de match: %s", e)
        return None, None


def series_para_casar(conn, atualizadas):
    """Séries com temporada sem match, mais as que acabaram de mudar."""
    sem_match = conn.execute(
        """SELECT DISTINCT s.series_id, se.title
             FROM seasons s
             JOIN series se USING (series_id)
             LEFT JOIN matches m USING (season_id)
            WHERE m.season_id IS NULL"""
    ).fetchall()
    alvos = {r["series_id"]: r["title"] for r in sem_match}
    alvos.update({s["series_id"]: s["series_title"] for s in atualizadas})
    return list(alvos.items())


def casar(conn, cliente, alvos, aviso):
    """Casa as temporadas das séries indicadas. Revisado não é tocado (ver db)."""
    total = 0
    for i, (series_id, titulo) in enumerate(alvos, 1):
        aviso(f"casando {titulo}", i, len(alvos))
        entrada = [
            {
                "season_id": r["season_id"],
                "season_number": r["season_number"],
                "season_title": r["title"],
                "total_episodes": r["total_episodes"],
                "years": (r["year_start"], r["year_end"]) if r["year_start"] else None,
            }
            for r in db.seasons_of(conn, series_id)
        ]
        if entrada:
            total += db.save_matches(conn, match_seasons(cliente, titulo, entrada))
    return total


def series_com_temporadas(conn):
    """Todas as séries que têm temporadas, para recasar do zero."""
    return [
        (r["series_id"], r["title"])
        for r in conn.execute(
            """SELECT DISTINCT se.series_id, se.title
                 FROM series se JOIN seasons s USING (series_id)
                ORDER BY se.title"""
        )
    ]


def rodar_match(conn, matcher=AUTO, todas=False, filtro="", progresso=None):
    """Match isolado, sem tocar na Crunchyroll.

    `todas=True` recasa tudo que não foi revisado — serve para refazer com a
    API do AniList o que foi casado contra o catálogo local."""
    aviso = progresso or (lambda *a, **k: None)
    fonte = None
    if matcher is AUTO:
        aviso("procurando o AniList", 0, 1)
        matcher, fonte = cliente_de_match()
    if matcher is None:
        return {"matches": 0, "fonte_match": None, "alvos": 0}

    alvos = series_com_temporadas(conn) if todas else series_para_casar(conn, [])
    if filtro:
        alvos = [(i, t) for i, t in alvos if filtro.lower() in (t or "").lower()]
    return {"matches": casar(conn, matcher, alvos, aviso),
            "fonte_match": fonte, "alvos": len(alvos)}


def run(cr, conn, force=False, ttl_horas=TTL_HORAS, progresso=None, matcher=AUTO):
    """Sincroniza a Crunchyroll e casa o que ficou sem correspondência.

    matcher=AUTO escolhe a fonte sozinho; None pula o match; um cliente
    explícito é usado como veio."""
    if not force:
        falta = minutos_ate_liberar(conn, ttl_horas)
        if falta:
            raise SyncBloqueado(falta)

    aviso = progresso or (lambda *a, **k: None)
    resumo = {"episodios": 0, "series": 0, "series_atualizadas": 0, "temporadas": 0,
              "matches": 0, "fonte_match": None, "incremental": False}

    # 1. histórico, parando onde o conhecido começa
    desde = marca_dagua(conn)
    resumo["incremental"] = desde is not None
    aviso("histórico", 0, 1)
    episodios = list(cr.watch_history(since=desde))
    if episodios:
        db.save_history(conn, episodios)
    resumo["episodios"] = len(episodios)

    # 2. escopo e contagens, em lote
    aviso("watchlist", 0, 1)
    entradas = {s["series_id"]: s for s in cr.watchlist()}
    ids = escopo(conn, list(entradas))
    objetos = cr.resolve_objects(ids)

    guardado = estado_guardado(conn)
    series, pendentes = [], []
    for series_id in ids:
        obj = objetos.get(series_id, {})
        meta = obj.get("series_metadata", {})
        entrada = entradas.get(series_id, {})
        atual = {
            "series_id": series_id,
            "series_title": obj.get("title") or _titulo_do_historico(conn, series_id),
            "availability": meta.get("availability_status", "unknown"),
            "total_episodes": int(meta.get("episode_count") or 0),
            "total_seasons": int(meta.get("season_count") or 0),
            "added_at": entrada.get("added_at"),
            "is_favorite": entrada.get("is_favorite", False),
            "in_watchlist": series_id in entradas,
        }
        series.append(atual)
        if atual["availability"] == "available" and precisa_temporadas(atual, guardado.get(series_id)):
            pendentes.append(atual)

    db.save_series(conn, series)
    resumo["series"] = len(series)
    resumo["series_atualizadas"] = len(pendentes)

    # 3. temporadas só do que mudou — a parte cara
    for i, serie in enumerate(pendentes, 1):
        aviso(serie["series_title"], i, len(pendentes))
        temporadas = cr.seasons(serie["series_id"])
        db.save_seasons(conn, serie["series_id"], temporadas)
        resumo["temporadas"] += len(temporadas)

    # 4. casar o que ficou sem correspondência, para gerar a fila de revisão
    fonte = None
    if matcher is AUTO:
        aviso("procurando o AniList", 0, 1)
        matcher, fonte = cliente_de_match()
    resumo["fonte_match"] = fonte
    if matcher is not None:
        resumo["matches"] = casar(conn, matcher, series_para_casar(conn, pendentes), aviso)

    db.set_setting(conn, ULTIMO_SYNC, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return resumo


def _titulo_do_historico(conn, series_id):
    """Série fora do catálogo não resolve no cms; o histórico ainda tem o nome."""
    linha = conn.execute(
        "SELECT series_title FROM watch_history WHERE series_id = ? AND series_title != '' LIMIT 1",
        [series_id],
    ).fetchone()
    return (linha["series_title"] if linha else None) or "unknown"
