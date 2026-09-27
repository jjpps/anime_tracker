"""CLI do anime-tracker: sync e leitura pelo terminal (largar/voltar é pela UI).

    python -m anime_tracker serve         # sobe o frontend e a API
    python -m anime_tracker crunchyroll   # busca histórico e temporadas (é o que o cron roda)
    python -m anime_tracker novidades     # lista o que saiu dos animes iniciados
"""

import argparse
import logging
import os
import sys

from . import db, novidades, sync
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
    try:
        with sync.registrando_erro(conn):
            cr = Crunchyroll().login(etp_rt)
            r = sync.run(cr, conn, force=args.force, ttl_horas=args.ttl, progresso=avisar)
    except sync.SyncBloqueado as e:
        sys.exit(f"{e}. Use --force para ignorar o intervalo.")
    limpar_linha()
    print(f"{r['episodios']} episódios novos, {r['series']} séries, "
          f"{r['temporadas']} temporadas atualizadas")


def cmd_novidades(args, conn):
    animes = novidades.lista(conn)
    for a in animes:
        partes = [f"Temporada nova: {t['title']} ({t['episodes']} eps)" for t in a["new_seasons"]]
        if a["continuation"]:
            c = a["continuation"]
            partes.append(f"Continuação: {c['episodes']} eps novos em {c['title']}")
        print(f"{a['title']} — {' · '.join(partes)}")
    print(f"\n{len(animes)} anime(s) com novidade")


def cmd_serve(args, conn):
    from .server import create_app

    conn.close()  # o servidor abre a própria conexão por request
    create_app(args.db).run(host=args.host, port=args.port, debug=args.debug)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="anime_tracker")
    parser.add_argument("--db", default=None, help="caminho do sqlite (padrão: ANIME_TRACKER_DB)")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("crunchyroll", help="busca histórico, temporadas e episódios")
    p.add_argument("--force", action="store_true", help="ignora o intervalo mínimo")
    p.add_argument("--ttl", type=int, default=sync.TTL_HORAS)

    sub.add_parser("novidades", help="temporadas novas e continuações dos animes iniciados")

    p = sub.add_parser("serve", help="sobe o frontend e a API")
    p.add_argument("--host", default="127.0.0.1")
    p.add_argument("--port", type=int, default=8000)
    p.add_argument("--debug", action="store_true")

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    load_env()
    conn = db.connect(args.db)
    try:
        {"crunchyroll": cmd_crunchyroll, "novidades": cmd_novidades,
         "serve": cmd_serve}[args.cmd](args, conn)
    except CrunchyrollError as e:
        sys.exit(f"\nCrunchyroll: {e}\nSe for erro de auth, o cookie etp_rt expirou.")
    except KeyboardInterrupt:
        sys.exit("\ninterrompido")
    finally:
        conn.close()


if __name__ == "__main__":
    main()
