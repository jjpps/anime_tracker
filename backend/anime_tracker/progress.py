"""Cálculo do que falta assistir: histórico x catálogo de temporadas.
"""

import collections


def watched_by_season(history):
    """(series_id, season_number) -> conjunto de episódios concluídos."""
    watched = collections.defaultdict(set)
    for ep in history:
        # sem número de episódio não dá para dizer qual foi assistido
        if ep["fully_watched"] and ep.get("episode_number") is not None:
            watched[(ep["series_id"], ep["season_number"])].add(ep["episode_number"])
    return watched


def series_status(series, seasons, watched):
    """Estado de cada temporada de uma série: assistidos vs total do catálogo."""
    out = []
    for season in seasons:
        seen = len(watched.get((series["series_id"], season["season_number"]), ()))
        total = season["total_episodes"]
        out.append(
            {
                **season,
                "watched": seen,
                # sem contagem oficial não dá para afirmar que está completa
                "complete": total > 0 and seen >= total,
                "started": seen > 0,
            }
        )
    return {
        "series_id": series["series_id"],
        "series_title": series["series_title"],
        "seasons_total": len(out),
        "seasons_complete": sum(s["complete"] for s in out),
        "pending": [s for s in out if not s["complete"]],
        "seasons": out,
    }
