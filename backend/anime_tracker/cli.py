"""CLI do anime-tracker — as mesmas features da API, sem interface.

    python -m anime_tracker serve                # sobe o frontend e a API
    python -m anime_tracker crunchyroll          # 1. busca dados da Crunchyroll
    python -m anime_tracker match mal|anilist    # 2. busca no provedor e casa
    python -m anime_tracker library              # 3. matches resolvidos
    python -m anime_tracker pending [provider]   # 4. pendentes de match
    python -m anime_tracker link <season_id> <provider> <id>   # 5. vincula
"""

import argparse
import logging
import os
import sys

from . import db, sync
from .anilist import AniListError
from .config import load_env
from .crunchyroll import Crunchyroll, CrunchyrollError


def avisar(texto, feito, total):
    """Progresso das tarefas longas, na mesma linha do terminal."""
    print(f"\r{feito}/{total} {texto[:40]:<42}", end="", file=sys.stderr)


def limpar_linha():
    print("\r" + " " * 60 + "\r", end="", file=sys.stderr)


def cmd_crunchyroll(args, conn):
    etp_rt = os.environ.get("CR_ETP_RT")
    if not etp_rt:
        sys.exit("defina CR_ETP_RT no .env")
    cr = Crunchyroll().login(etp_rt)
    try:
        r = sync.run(cr, conn, force=args.force, ttl_horas=args.ttl,
                     progresso=avisar, matcher=None)
    except sync.SyncBloqueado as e:
        sys.exit(f"{e}. Use --force para ignorar o intervalo.")
    limpar_linha()
    print(f"{r['episodios']} episódios novos, {r['series']} séries, "
          f"{r['temporadas']} temporadas atualizadas")


def cmd_match(args, conn):
    r = sync.rodar_match(conn, todas=args.todas, filtro=args.filtro,
                         provider=args.provider, progresso=avisar)
    limpar_linha()
    if r["fonte_match"] is None:
        sys.exit("sem fonte de match: API fora do ar e o catálogo local falhou")
    print(f"{r['matches']} temporadas casadas em {r['alvos']} séries "
          f"(fonte: {r['fonte_match']})")
    print(f"{len(db.pendentes(conn))} pendente(s) de match")


def cmd_library(args, conn):
    linhas = db.biblioteca(conn)
    for r in linhas:
        print(f"{r['series_title']} T{r['season_number']} [{r['providers']}] "
              f"-> {r['anilist_title'] or r['mal_title']}")
    print(f"\n{len(linhas)} temporada(s) na biblioteca")


def cmd_pending(args, conn):
    linhas = db.pendentes(conn)
    for r in linhas:
        alvo = r["anilist_title"] or r["mal_title"] or "SEM CORRESPONDÊNCIA"
        dup = f" [mesma obra da T{r['duplicate_of']}]" if r["duplicate_of"] else ""
        print(f"{r['season_id']}  conf={r['confidence']:.2f}")
        print(f"    {r['series_title']} T{r['season_number']} -> {alvo}{dup}")
    print(f"\n{len(linhas)} pendente(s)")


def cmd_link(args, conn):
    n = db.vincular(conn, args.season_id, args.provider, args.provider_id)
    print(f"{args.season_id} -> {args.provider} {args.provider_id}" if n
          else "season_id não encontrado")


def cmd_serve(args, conn):
    from .server import create_app

    conn.close()  # o servidor abre a própria conexão por request
    create_app(args.db).run(host=args.host, port=args.port, debug=args.debug)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="anime_tracker")
    parser.add_argument("--db", default=None, help="caminho do sqlite (padrão: ANIME_TRACKER_DB)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("crunchyroll", help="1. busca watchlist, histórico e temporadas")
    p.add_argument("--force", action="store_true", help="ignora o intervalo mínimo")
    p.add_argument("--ttl", type=int, default=sync.TTL_HORAS)

    p = sub.add_parser("match", help="2. busca no provedor e casa com a nossa base")
    p.add_argument("provider", choices=db.PROVIDERS)
    p.add_argument("filtro", nargs="?", default="", help="filtra por trecho do título")
    p.add_argument("--todas", action="store_true", help="recasa o que já tem vínculo")

    sub.add_parser("library", help="3. matches resolvidos")

    sub.add_parser("pending", help="4. pendentes de match")

    p = sub.add_parser("link", help="5. vincula um id do provedor à temporada")
    p.add_argument("season_id")
    p.add_argument("provider", choices=db.PROVIDERS)
    p.add_argument("provider_id", type=int)

    p = sub.add_parser("serve", help="sobe o frontend e a API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--debug", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    load_env()
    conn = db.connect(args.db)
    try:
        {"crunchyroll": cmd_crunchyroll, "match": cmd_match, "library": cmd_library,
         "pending": cmd_pending, "link": cmd_link, "serve": cmd_serve}[args.cmd](args, conn)
    except AniListError as e:
        sys.exit(f"\nAniList indisponível: {e}")
    except CrunchyrollError as e:
        sys.exit(f"\nCrunchyroll: {e}\nSe for erro de auth, o cookie etp_rt expirou.")
    except KeyboardInterrupt:
        sys.exit("\ninterrompido")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
