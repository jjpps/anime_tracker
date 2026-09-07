"""Cruza watchlist + histórico + temporadas do catálogo e diz o que falta assistir.

Uso:
    export CR_ETP_RT="<cookie etp_rt>"
    python pending.py                # tudo que tem temporada pendente
    python pending.py mushoku        # filtra por trecho do título
    python pending.py --json         # saída estruturada
"""

import collections
import json
import os
import sys

from crunchyroll import Crunchyroll


def watched_by_season(history):
    """(series_id, season_number) -> conjunto de episódios concluídos."""
    watched = collections.defaultdict(set)
    for ep in history:
        if ep["fully_watched"]:
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


def main():
    args = [a for a in sys.argv[1:] if a != "--json"]
    as_json = "--json" in sys.argv
    needle = args[0].lower() if args else ""

    etp_rt = os.environ.get("CR_ETP_RT")
    if not etp_rt:
        sys.exit("defina CR_ETP_RT com o cookie etp_rt do crunchyroll.com")

    cr = Crunchyroll().login(etp_rt)
    watched = watched_by_season(cr.watch_history())
    alvos = [
        s for s in cr.watchlist()
        if s["availability"] == "available" and needle in s["series_title"].lower()
    ]

    report = []
    for i, series in enumerate(alvos, 1):
        print(f"\r{i}/{len(alvos)} séries...", end="", file=sys.stderr)
        report.append(series_status(series, cr.seasons(series["series_id"]), watched))
    print("\r" + " " * 30 + "\r", end="", file=sys.stderr)

    if as_json:
        json.dump(report, sys.stdout, ensure_ascii=False, indent=2)
        return

    atrasados = [r for r in report if r["pending"] and r["seasons_complete"]]
    for r in sorted(atrasados, key=lambda r: -len(r["pending"])):
        print(f"\n{r['series_title']}  ({r['seasons_complete']}/{r['seasons_total']} temporadas completas)")
        for s in r["pending"]:
            falta = s["total_episodes"] - s["watched"]
            marca = "em andamento" if s["started"] else "não iniciada"
            # season_number 0 = especiais/OVA, e a série pode ter várias — o título desempata
            rotulo = f"T{s['season_number']}" if s["season_number"] else s["season_title"] or "Especiais"
            print(f"  {rotulo}: {s['watched']}/{s['total_episodes']} — faltam {falta} ({marca})")
    if not atrasados:
        print("nada pendente nas séries com temporada já concluída")


if __name__ == "__main__":
    main()
