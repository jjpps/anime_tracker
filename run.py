"""Atalho para rodar o backend da raiz do repositório.

    python run.py serve          # frontend + API em localhost:8000
    python run.py crunchyroll    # busca histórico, temporadas e episódios (o que o cron roda)
    python run.py novidades      # temporadas novas e continuações no terminal

Equivale a `cd backend && python -m anime_tracker ...`. Existe porque a raiz do
repo e o pacote têm o mesmo nome, e rodar `python -m anime_tracker` daqui acha
a pasta em vez do pacote.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from anime_tracker.cli import main  # noqa: E402

main()
