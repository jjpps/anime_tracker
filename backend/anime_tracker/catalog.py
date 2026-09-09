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
MAL_URL = re.compile(r"myanimelist\.net/anime/(\d+)")


class CatalogoAusente(Exception):
    """Arquivo do catálogo local não encontrado."""


def baixar(destino=None, progresso=None):
    """Baixa o catálogo. O app busca a própria dependência em vez de mandar
    o usuário rodar curl — o arquivo é detalhe de implementação nosso."""
    import requests

    caminho = destino or caminho_db()
    os.makedirs(os.path.dirname(caminho) or ".", exist_ok=True)
    aviso = progresso or (lambda *a, **k: None)
    log.info("baixando catálogo de %s", URL_DOWNLOAD)

    parcial = caminho + ".parcial"
    with requests.get(URL_DOWNLOAD, stream=True, timeout=300) as resp:
        resp.raise_for_status()
        total = int(resp.headers.get("Content-Length") or 0)
        baixado = 0
        with open(parcial, "wb") as fh:
            for bloco in resp.iter_content(chunk_size=1 << 20):
                fh.write(bloco)
                baixado += len(bloco)
                aviso("baixando catálogo", baixado // (1 << 20), total // (1 << 20))
    # só troca no fim: download interrompido não pode virar arquivo meio escrito
    os.replace(parcial, caminho)
    log.info("catálogo salvo em %s (%.1f MB)", caminho, baixado / 1e6)
    return caminho


def garantir(destino=None, progresso=None):
    """Caminho do catálogo, baixando se ainda não existe."""
    caminho = destino or caminho_db()
    if not os.path.exists(caminho):
        baixar(caminho, progresso)
    return caminho


def _id(padrao, sources):
    for s in sources:
        achado = padrao.search(s)
        if achado:
            return int(achado.group(1))
    return None


def mapa_anilist_para_mal(path=None):
    """anilist_id -> (mal_id, título, episódios, tipo, status).

    `status` é ONGOING/FINISHED e decide se "assisti tudo que existe" quer
    dizer "terminei" ou "estou em dia".

    O catálogo cruza os dois ids, o que evita depender da busca por título do
    MAL — que hoje está fora e, mesmo no ar, rejeita títulos longos."""
    caminho = caminho_db(path)
    if not os.path.exists(caminho):
        raise CatalogoAusente(
            f"catálogo local não encontrado em {caminho}\n"
            f"  make db\n"
            f"  ou: curl -L -o {caminho} {URL_DOWNLOAD}"
        )
    with open(caminho, encoding="utf-8") as fh:
        entries = json.load(fh)["data"]

    mapa = {}
    for e in entries:
        anilist_id = _id(ANILIST_URL, e["sources"])
        mal_id = _id(MAL_URL, e["sources"])
        if anilist_id and mal_id:
            mapa[anilist_id] = (mal_id, e.get("title"), e.get("episodes"),
                                e.get("type"), e.get("status"))
    log.info("mapa anilist->mal: %d obras cruzadas de %d", len(mapa), len(entries))
    return mapa


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
