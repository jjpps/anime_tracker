"""Atalho para rodar o backend da raiz do repositório.

    python run.py serve          # frontend + API em localhost:8000
    python run.py crunchyroll    # 1. busca dados da Crunchyroll
    python run.py match mal      # 2. busca no provedor e casa
    python run.py library        # 3. matches feitos
    python run.py pending        # 4. pendentes de match
    python run.py link <season_id> mal <id>   # 5. vincula na mão

Equivale a `cd backend && python -m anime_tracker ...`. Existe porque a raiz do
repo e o pacote têm o mesmo nome, e rodar `python -m anime_tracker` daqui acha
a pasta em vez do pacote.
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "backend"))

from anime_tracker.cli import main  # noqa: E402

main()
