"""Enriquecimento da tela de detalhe com o AniList. Só exibição (docs/adr/0002):
nada daqui decide Novidade."""

import json
from datetime import datetime, timedelta, timezone

import requests

from . import db

URL = "https://graphql.anilist.co"
TTL = timedelta(days=7)
CAMPOS = """id siteUrl description(asHtml: true) averageScore genres status
  episodes seasonYear bannerImage coverImage { large } title { romaji english }"""
POR_ID = f"query($id: Int) {{ Media(id: $id, type: ANIME) {{ {CAMPOS} }} }}"
POR_TITULO = (f"query($q: String) {{ Media(search: $q, type: ANIME, sort: SEARCH_MATCH) "
              f"{{ {CAMPOS} }} }}")


class AniListErro(Exception):
    pass


def _buscar(query, variaveis):
    try:
        r = requests.post(URL, json={"query": query, "variables": variaveis}, timeout=10)
    except requests.RequestException as e:
        raise AniListErro(str(e))
    # 404 do AniList é "não achou"; o resto é falha e não pode ir para o cache
    if r.status_code == 404:
        return None
    if not r.ok:
        raise AniListErro(f"AniList respondeu {r.status_code}")
    return (r.json().get("data") or {}).get("Media")


def detalhe(conn, series_id, titulo, buscar=_buscar):
    """Dados do AniList do anime, ou None se não achou. Levanta AniListErro em
    falha de rede: quem chama mostra só a CR, e nada é gravado."""
    guardado = db.get_anilist(conn, series_id)
    if guardado and datetime.fromisoformat(guardado["fetched_at"]) + TTL > datetime.now(timezone.utc):
        return json.loads(guardado["data"]) if guardado["data"] else None

    if guardado and guardado["anilist_id"]:
        media = buscar(POR_ID, {"id": guardado["anilist_id"]})
    else:
        media = buscar(POR_TITULO, {"q": titulo})
    db.save_anilist(conn, series_id, media and media["id"], media and json.dumps(media))
    return media
