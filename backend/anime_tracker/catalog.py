"""Catálogo local do AniList (base do manami-project), com a mesma interface
do cliente da API.

Serve para casar temporadas sem depender da API — que hoje responde 403 — e
para calibrar o matcher contra títulos reais. `make db` baixa o arquivo.
"""

import collections
import json
import os
import re
import sys

from .anilist import normalize

DB = os.environ.get("ANIME_DB_JSON", ".cache/anime-db.json")
ANILIST_URL = re.compile(r"anilist\.co/anime/(\d+)")


class OfflineIndex:
    """Mesma interface de AniList.search_many, servindo do catálogo local.

Trocável por anilist.AniList sem o chamador saber a diferença."""

    def __init__(self, path=DB):
        if not os.path.exists(path):
            sys.exit(f"falta {path} — rode: make db")
        entries = json.load(open(path))["data"]

        self.media = []
        self.por_token = collections.defaultdict(list)
        for e in entries:
            achado = next((ANILIST_URL.search(s) for s in e["sources"] if ANILIST_URL.search(s)), None)
            if not achado:
                continue  # sem id do AniList não serve para o nosso mapa
            titulos = [e["title"], *e.get("synonyms", [])]
            i = len(self.media)
            self.media.append({
                "id": int(achado.group(1)),
                "title": {"romaji": e["title"], "english": None, "native": None},
                "synonyms": e.get("synonyms", []),
                "format": e.get("type"),
                "episodes": e.get("episodes"),
                "seasonYear": (e.get("animeSeason") or {}).get("year"),
                "siteUrl": f"https://anilist.co/anime/{achado.group(1)}",
            })
            for token in {t for titulo in titulos for t in normalize(titulo).split()}:
                self.por_token[token].append(i)

    def search_many(self, terms):
        return {t: self._search(t) for t in terms}

    def _search(self, term):
        """Candidatos = obras que compartilham tokens com a busca.

        Tokens muito comuns ('no', 'season') puxariam meio catálogo, então
        pesam menos: ordenamos por quantidade de tokens em comum."""
        tokens = normalize(term).split()
        contagem = collections.Counter()
        for token in tokens:
            indices = self.por_token.get(token, [])
            if len(indices) > 3000:
                continue  # token genérico demais para discriminar
            contagem.update(indices)
        return [self.media[i] for i, _ in contagem.most_common(30)]
