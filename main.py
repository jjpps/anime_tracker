"""Busca histórico + watchlist do Crunchyroll e joga como JSON no stdout.

Uso:
    export CR_ETP_RT="<cookie etp_rt>"
    python main.py history > history.json
    python main.py watchlist > watchlist.json
"""

import json
import os
import sys

from crunchyroll import Crunchyroll

etp_rt = os.environ.get("CR_ETP_RT")
if not etp_rt:
    sys.exit("defina CR_ETP_RT com o cookie etp_rt do crunchyroll.com")

cr = Crunchyroll().login(etp_rt)
what = sys.argv[1] if len(sys.argv) > 1 else "history"
source = cr.watchlist() if what == "watchlist" else cr.watch_history()
json.dump(list(source), sys.stdout, ensure_ascii=False, indent=2)
