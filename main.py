"""Busca histórico + watchlist do Crunchyroll e joga como JSON no stdout.

Uso:
    export CR_ETP_RT="<cookie etp_rt>"
    python main.py > crunchyroll.json     # os dois
    python main.py history                # só o histórico
    python main.py watchlist              # só a watchlist
"""

import json
import os
import sys

from crunchyroll import Crunchyroll

etp_rt = os.environ.get("CR_ETP_RT")
if not etp_rt:
    sys.exit("defina CR_ETP_RT com o cookie etp_rt do crunchyroll.com")

cr = Crunchyroll().login(etp_rt)
what = sys.argv[1] if len(sys.argv) > 1 else "all"
out = {}
if what in ("all", "history"):
    out["history"] = list(cr.watch_history())
if what in ("all", "watchlist"):
    out["watchlist"] = list(cr.watchlist())
if not out:
    sys.exit(f"argumento inválido: {what!r} (use history, watchlist ou nada)")

print(f"{len(out.get('history', []))} episódios, {len(out.get('watchlist', []))} séries",
      file=sys.stderr)
json.dump(out, sys.stdout, ensure_ascii=False, indent=2)
