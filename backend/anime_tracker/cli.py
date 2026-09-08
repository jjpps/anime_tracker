"""CLI do anime-tracker.

    python -m anime_tracker sync            # Crunchyroll -> sqlite
    python -m anime_tracker match           # casa temporadas com o AniList
    python -m anime_tracker match --offline # usa o catálogo local (.cache/anime-db.json)
    python -m anime_tracker review          # fila de revisão
    python -m anime_tracker review confirm <season_id>
    python -m anime_tracker pending         # o que falta assistir
    python -m anime_tracker stats
    python -m anime_tracker serve           # frontend + API em localhost:8000
"""

import argparse
import os
import sys

from . import db, sync
from .config import load_env
from .anilist import AniList, AniListError, match_seasons
from .crunchyroll import Crunchyroll, CrunchyrollError
from .progress import series_status, watched_by_season


def _cr():
    etp_rt = os.environ.get("CR_ETP_RT")
    if not etp_rt:
        sys.exit("defina CR_ETP_RT com o cookie etp_rt do crunchyroll.com")
    return Crunchyroll().login(etp_rt)


def _progresso(i, total, texto=""):
    print(f"\r{i}/{total} {texto[:40]:<42}", end="", file=sys.stderr)


def cmd_sync(args, conn):
    try:
        r = sync.run(_cr(), conn, force=args.force, ttl_horas=args.ttl,
                     progresso=lambda texto, i, total: _progresso(i, total, texto))
    except sync.SyncBloqueado as e:
        sys.exit(f"{e}. Use --force para ignorar o intervalo.")
    print("\r" + " " * 60 + "\r", end="", file=sys.stderr)
    modo = "incremental" if r["incremental"] else "completo"
    print(f"sync {modo}: {r['episodios']} episódios novos, {r['series']} séries, "
          f"{r['series_atualizadas']} com temporadas rebuscadas ({r['temporadas']} temporadas)")


def cmd_match(args, conn):
    if args.offline:
        from .catalog import OfflineIndex

        client = OfflineIndex()
    else:
        client = AniList()

    series = conn.execute(
        "SELECT series_id, title FROM series WHERE availability = 'available'"
    ).fetchall()
    if args.filtro:
        series = [s for s in series if args.filtro.lower() in s["title"].lower()]

    total = 0
    for i, s in enumerate(series, 1):
        _progresso(i, len(series), s["title"])
        seasons = db.seasons_of(conn, s["series_id"])
        if not seasons:
            continue
        entrada = [
            {
                "season_id": r["season_id"],
                "season_number": r["season_number"],
                "season_title": r["title"],
                "total_episodes": r["total_episodes"],
                "years": (r["year_start"], r["year_end"]) if r["year_start"] else None,
            }
            for r in seasons
        ]
        total += db.save_matches(conn, match_seasons(client, s["title"], entrada))
    print("\r" + " " * 60 + "\r", end="", file=sys.stderr)
    print(f"{total} temporadas processadas")
    cmd_stats(args, conn)


def cmd_review(args, conn):
    if args.acao in ("confirm", "reject"):
        if not args.season_id:
            sys.exit(f"uso: review {args.acao} <season_id> [anilist_id]")
        status = "confirmed" if args.acao == "confirm" else "rejected"
        n = db.set_review(conn, args.season_id, status, args.anilist_id)
        print(f"{n} match(es) marcado(s) como {status}" if n else "season_id não encontrado")
        return

    linhas = db.reviewed(conn, args.limit) if args.acao == "done" else db.pending_review(conn, args.limit)
    if not linhas:
        print("nada aqui")
        return
    for r in linhas:
        alvo = r["anilist_title"] or "SEM MATCH"
        dup = f" [dup de T{r['duplicate_of']}]" if r["duplicate_of"] else ""
        marca = r["review_status"] if args.acao == "done" else f"conf={r['confidence']:.2f}"
        print(f"{r['season_id']}  {marca}")
        print(f"    {r['series_title']} T{r['season_number']} ({r['cr_episodes']} eps)"
              f" -> {alvo} ({r['anilist_episodes']} eps){dup}")
    print(f"\n{len(linhas)} registro(s)")


def cmd_pending(args, conn):
    """Temporadas que faltam assistir, direto do banco."""
    historico = [dict(r) for r in conn.execute("SELECT * FROM watch_history").fetchall()]
    for e in historico:
        e["fully_watched"] = bool(e["fully_watched"])
    assistidos = watched_by_season(historico)

    series = conn.execute(
        "SELECT series_id, title FROM series WHERE availability = 'available' ORDER BY title"
    ).fetchall()
    for s in series:
        if args.filtro and args.filtro.lower() not in s["title"].lower():
            continue
        seasons = [
            {
                "season_number": r["season_number"],
                "season_title": r["title"],
                "total_episodes": r["total_episodes"],
            }
            for r in db.seasons_of(conn, s["series_id"])
        ]
        if not seasons:
            continue
        estado = series_status({"series_id": s["series_id"], "series_title": s["title"]},
                               seasons, assistidos)
        if not estado["pending"] or not estado["seasons_complete"]:
            continue
        print(f"\n{s['title']}  ({estado['seasons_complete']}/{estado['seasons_total']} temporadas completas)")
        for t in estado["pending"]:
            falta = t["total_episodes"] - t["watched"]
            marca = "em andamento" if t["started"] else "não iniciada"
            rotulo = f"T{t['season_number']}" if t["season_number"] else (t["season_title"] or "Especiais")
            print(f"  {rotulo}: {t['watched']}/{t['total_episodes']} — faltam {falta} ({marca})")


def cmd_serve(args, conn):
    from .server import create_app

    conn.close()  # o servidor abre a própria conexão por request
    create_app(args.db).run(host=args.host, port=args.port, debug=args.debug)


def cmd_stats(args, conn):
    s = db.stats(conn)
    print(f"séries {s['series']} | temporadas {s['seasons']} | episódios {s['episodes']}")
    print(f"matches: {s['matched']} com anilist_id | "
          f"{s['pending']} a revisar, {s['confirmed']} confirmados, {s['rejected']} rejeitados")


def main(argv=None):
    parser = argparse.ArgumentParser(prog="anime_tracker")
    parser.add_argument("--db", default=None, help="caminho do sqlite (padrão: ANIME_TRACKER_DB)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("sync", help="importa da Crunchyroll o que mudou desde o último sync")
    p.add_argument("--force", action="store_true", help="ignora o intervalo mínimo")
    p.add_argument("--ttl", type=int, default=sync.TTL_HORAS,
                   help="horas mínimas entre syncs (padrão: %(default)s)")

    p = sub.add_parser("match", help="casa temporadas da CR com obras do AniList")
    p.add_argument("filtro", nargs="?", default="", help="filtra por trecho do título")
    p.add_argument("--offline", action="store_true", help="usa o catálogo local em vez da API")

    p = sub.add_parser("review", help="fila de revisão dos matches")
    p.add_argument("acao", nargs="?", default="list", choices=["list", "done", "confirm", "reject"])
    p.add_argument("season_id", nargs="?")
    p.add_argument("anilist_id", nargs="?", type=int)
    p.add_argument("--limit", type=int, default=20)

    p = sub.add_parser("pending", help="temporadas que faltam assistir")
    p.add_argument("filtro", nargs="?", default="")

    sub.add_parser("stats", help="resumo do banco")

    p = sub.add_parser("serve", help="sobe o frontend e a API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--debug", action="store_true")

    args = parser.parse_args(argv)
    load_env()  # antes de qualquer leitura de os.environ
    conn = db.connect(args.db)
    try:
        {"sync": cmd_sync, "match": cmd_match, "review": cmd_review,
         "pending": cmd_pending, "stats": cmd_stats, "serve": cmd_serve}[args.cmd](args, conn)
    except AniListError as e:
        # falha da API deles não é bug nosso: mensagem clara em vez de traceback
        sys.exit(f"\nAniList indisponível: {e}\n"
                 f"Alternativa: `match --offline` usa o catálogo local (baixe com make db).")
    except CrunchyrollError as e:
        sys.exit(f"\nCrunchyroll: {e}\n"
                 f"Se for erro de auth, o cookie etp_rt expirou — pegue um novo no navegador.")
    except KeyboardInterrupt:
        sys.exit("\ninterrompido")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
