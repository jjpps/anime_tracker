"""Valida o matcher contra o catálogo real do AniList, sem depender da API.

A base do manami-project traz os mesmos IDs do AniList com títulos e sinônimos
reais. Serve para calibrar o matcher enquanto a API está fora — a integração de
verdade continua sendo anilist.AniList.

    make db     # baixa .cache/anime-db.json
    python offline_check.py            # relatório sobre a watchlist salva
    python offline_check.py mushoku    # filtra por título
"""

import collections
import json
import os
import re
import sys

from anilist import match_seasons, normalize

DB = ".cache/anime-db.json"
ANILIST_URL = re.compile(r"anilist\.co/anime/(\d+)")


class OfflineIndex:
    """Mesma interface de AniList.search_many, servindo do catálogo local."""

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


def main():
    needle = (sys.argv[1] if len(sys.argv) > 1 else "").lower()
    dados = json.load(open("crunchyroll.json")) if os.path.exists("crunchyroll.json") else None
    if not dados:
        sys.exit("falta crunchyroll.json — rode: CR_ETP_RT=... python main.py > crunchyroll.json")
    seasons_por_serie = json.load(open(".cache/seasons.json")) if os.path.exists(".cache/seasons.json") else {}
    if not seasons_por_serie:
        sys.exit("falta .cache/seasons.json — rode: CR_ETP_RT=... python offline_check.py --fetch-seasons")

    index = OfflineIndex()
    total = casados = revisar = 0
    for serie in dados["watchlist"]:
        if needle not in serie["series_title"].lower():
            continue
        seasons = seasons_por_serie.get(serie["series_id"], [])
        if not seasons:
            continue
        resultado = match_seasons(index, serie["series_title"], seasons)
        total += len(resultado)
        casados += sum(1 for s in resultado if s["anilist_id"])
        revisar += sum(1 for s in resultado if s["anilist_id"] and s["needs_review"])

        falhas = [s for s in resultado if not s["anilist_id"]]
        if needle or falhas:
            print(f"\n{serie['series_title']}")
            for s in resultado:
                marca = "  " if s["anilist_id"] and not s["needs_review"] else "??" if s["anilist_id"] else "XX"
                alvo = s["anilist_title"] or "SEM MATCH"
                print(f" {marca} T{s['season_number']} ({s['cr_episodes']} eps) -> {alvo} "
                      f"[{s['anilist_episodes']} eps] conf={s['confidence']}")

    pct = 100 * casados / total if total else 0
    print(f"\n{casados}/{total} temporadas casadas ({pct:.0f}%), {revisar} com confiança baixa")


def fetch_seasons():
    """Baixa e salva as temporadas de cada série da watchlist (cache p/ iterar offline)."""
    from crunchyroll import Crunchyroll

    cr = Crunchyroll().login(os.environ["CR_ETP_RT"])
    dados = json.load(open("crunchyroll.json"))
    out = {}
    for i, s in enumerate(dados["watchlist"], 1):
        print(f"\r{i}/{len(dados['watchlist'])}", end="", file=sys.stderr)
        if s["availability"] == "available":
            out[s["series_id"]] = cr.seasons(s["series_id"])
    os.makedirs(".cache", exist_ok=True)
    json.dump(out, open(".cache/seasons.json", "w"), ensure_ascii=False)
    print(f"\r.cache/seasons.json: {len(out)} séries", file=sys.stderr)


if __name__ == "__main__":
    fetch_seasons() if "--fetch-seasons" in sys.argv else main()
