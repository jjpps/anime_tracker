"""Regra do sync incremental.

O gargalo não é o histórico, são as temporadas: listar as temporadas de uma
série é 1 chamada, mas a faixa de anos exige 1 chamada por temporada — ~170 no
total. Então a regra é detectar barato o que mudou e só aí pagar o caro.

Camadas:
  1. histórico incremental, parando na marca d'água do último sync;
  2. escopo = watchlist ∪ séries distintas do histórico, resolvidas em lote
     (3 chamadas para 110 séries) — traz episode_count/season_count;
  3. temporadas rebuscadas só para série cuja contagem mudou ou que nunca foi
     sincronizada.

`is_complete` da temporada NÃO serve como sinal: a CR devolve False até para
temporada encerrada há anos.
"""

from datetime import datetime, timedelta, timezone

from . import db

TTL_HORAS = 6
# uma folga na marca d'água custa uma página e cobre desordem na borda
OVERLAP = timedelta(days=1)
ULTIMO_SYNC = "last_sync_at"


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


def run(cr, conn, force=False, ttl_horas=TTL_HORAS, progresso=None):
    """Executa o sync incremental. Devolve o resumo do que mudou."""
    if not force:
        falta = minutos_ate_liberar(conn, ttl_horas)
        if falta:
            raise SyncBloqueado(falta)

    aviso = progresso or (lambda *a, **k: None)
    resumo = {"episodios": 0, "series": 0, "series_atualizadas": 0, "temporadas": 0,
              "incremental": False}

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

    db.set_setting(conn, ULTIMO_SYNC, datetime.now(timezone.utc).isoformat(timespec="seconds"))
    return resumo


def _titulo_do_historico(conn, series_id):
    """Série fora do catálogo não resolve no cms; o histórico ainda tem o nome."""
    linha = conn.execute(
        "SELECT series_title FROM watch_history WHERE series_id = ? AND series_title != '' LIMIT 1",
        [series_id],
    ).fetchone()
    return (linha["series_title"] if linha else None) or "unknown"
