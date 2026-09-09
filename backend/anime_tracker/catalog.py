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


_memo = {}


def carregar(path=None):
    """Obras do catálogo, lidas uma vez por caminho.

    São 62 MB de JSON e dois consumidores (o índice de busca e o mapa
    anilist->mal); parsear duas vezes custava alguns segundos à toa."""
    caminho = caminho_db(path)
    if caminho not in _memo:
        if not os.path.exists(caminho):
            raise CatalogoAusente(f"catálogo local não encontrado em {caminho}")
        with open(caminho, encoding="utf-8") as fh:
            _memo[caminho] = json.load(fh)["data"]
        log.info("catálogo local: %d obras de %s", len(_memo[caminho]), caminho)
    return _memo[caminho]


def mapa_anilist_para_mal(path=None):
    """anilist_id -> (mal_id, título, episódios, tipo, status).

    `status` é ONGOING/FINISHED e decide se "assisti tudo que existe" quer
    dizer "terminei" ou "estou em dia".

    O catálogo cruza os dois ids, o que evita depender da busca por título do
    MAL — que hoje está fora e, mesmo no ar, rejeita títulos longos."""
    entries = carregar(path)
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


SITE = {"anilist": "https://anilist.co/anime/{}",
        "mal": "https://myanimelist.net/anime/{}"}


class OfflineIndex:
    """Mesma interface de AniList.search_many, servindo do catálogo local.

    `provider` escolhe de quem é o id devolvido: as obras e os títulos são os
    mesmos, muda o identificador que vai para o banco. Obra sem id do provedor
    escolhido não entra — casar com ela produziria um vínculo que não dá para
    exportar."""

    def __init__(self, path=None, provider="anilist"):
        if provider not in SITE:
            raise ValueError(f"provider inválido: {provider}")
        # exceção, não sys.exit: isso também roda em thread do servidor
        entries = carregar(path)
        self.provider = provider
        padrao = ANILIST_URL if provider == "anilist" else MAL_URL
        self.media = []
        self.por_token = collections.defaultdict(list)
        for e in entries:
            ident = _id(padrao, e["sources"])
            if not ident:
                continue
            titulos = [e["title"], *e.get("synonyms", [])]
            i = len(self.media)
            self.media.append({
                "id": ident,
                "title": {"romaji": e["title"], "english": None, "native": None},
                "synonyms": e.get("synonyms", []),
                "format": e.get("type"),
                "episodes": e.get("episodes"),
                "seasonYear": (e.get("animeSeason") or {}).get("year"),
                "siteUrl": SITE[provider].format(ident),
                "status": e.get("status"),
            })
            for token in {t for titulo in titulos for t in normalize(titulo).split()}:
                self.por_token[token].append(i)
        log.info("índice %s: %d obras", provider, len(self.media))

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
