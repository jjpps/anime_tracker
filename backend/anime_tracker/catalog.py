"""Catálogo local do AniList (base do manami-project), com a mesma interface
do cliente da API.

Serve para casar temporadas sem depender da API — que hoje responde 403 — e
para calibrar o matcher contra títulos reais. `make db` baixa o arquivo (ou o
curl equivalente, no Windows).
"""

import collections
import json
import logging
import os
import re

from .anilist import normalize
from .config import RAIZ

log = logging.getLogger("anime_tracker.catalog")

DB_PADRAO = ".cache/anime-db.json"
URL_DOWNLOAD = ("https://github.com/manami-project/anime-offline-database/"
                "releases/download/2026-27/anime-offline-database-minified.json")
ANILIST_URL = re.compile(r"anilist\.co/anime/(\d+)")


class CatalogoAusente(Exception):
    """Arquivo do catálogo local não encontrado."""


def caminho_db(path=None):
    """Resolvido na chamada e ancorado na raiz, como o caminho do banco.

    Relativo ao cwd faria `match --offline` achar o arquivo só se rodado do
    diretório certo."""
    caminho = path or os.environ.get("ANIME_DB_JSON") or DB_PADRAO
    if os.path.isabs(caminho):
        return caminho
    return os.path.join(RAIZ, caminho)


class OfflineIndex:
    """Mesma interface de AniList.search_many, servindo do catálogo local.

Trocável por anilist.AniList sem o chamador saber a diferença."""

    def __init__(self, path=None):
        caminho = caminho_db(path)
        if not os.path.exists(caminho):
            # exceção, não sys.exit: isso também roda em thread do servidor
            raise CatalogoAusente(
                f"catálogo local não encontrado em {caminho}\n"
                f"  make db\n"
                f"  ou: curl -L -o {caminho} {URL_DOWNLOAD}"
            )
        with open(caminho, encoding="utf-8") as fh:
            entries = json.load(fh)["data"]

        log.info("catálogo local: %d obras de %s", len(entries), caminho)
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
