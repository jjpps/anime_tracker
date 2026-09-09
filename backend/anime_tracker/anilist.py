"""Cliente da API do AniList e o matcher temporada -> obra.

O problema central: a Crunchyroll agrupa tudo sob uma série com N temporadas;
o AniList trata cada temporada como uma obra separada. Então a unidade de match
é a TEMPORADA da CR, não a série.

Quem orquestra é sync.py; aqui só há o cliente e as funções puras de match.
"""

import difflib
import json
import logging
import os
import re
import time

import requests

log = logging.getLogger("anime_tracker.anilist")

GRAPHQL = "https://graphql.anilist.co"
CACHE = "anilist_cache.json"
# 5 buscas por request via aliases: 145 séries cabem em poucas dezenas de chamadas
BATCH = 5
# a API está degradada em 30/min (era 90); o header manda, isto é só o palpite
# inicial até a primeira resposta chegar
LIMITE_PADRAO = 30
MAX_TENTATIVAS = 3
# abaixo disso o match não é confiável o bastante para gravar sem revisão
THRESHOLD = 0.75
IGNORED_FORMATS = {"MUSIC", "MANGA", "NOVEL", "ONE_SHOT"}

MEDIA_FIELDS = """
    id
    title { romaji english native }
    synonyms
    format
    episodes
    seasonYear
    siteUrl
"""


class AniListError(Exception):
    pass


class AniList:
    def __init__(self, cache_path=CACHE):
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": "anime-tracker/0.1",
            "Content-Type": "application/json",
            "Accept": "application/json",
        })
        self.cache_path = cache_path
        self.cache = json.load(open(cache_path)) if os.path.exists(cache_path) else {}
        self.limite = LIMITE_PADRAO
        self.restante = None
        self._proxima_chamada = 0.0

    def search_many(self, terms):
        """Busca vários termos por request usando aliases GraphQL. Respeita o cache."""
        pendentes = [t for t in dict.fromkeys(terms) if t not in self.cache]
        if pendentes:
            log.info("buscando %d termo(s) em %d request(s); %d já em cache",
                     len(pendentes), -(-len(pendentes) // BATCH), len(terms) - len(pendentes))
        for i in range(0, len(pendentes), BATCH):
            lote = pendentes[i : i + BATCH]
            aliases = " ".join(
                f'a{n}: Page(perPage: 8) {{ media(search: $s{n}, type: ANIME) {{ {MEDIA_FIELDS} }} }}'
                for n in range(len(lote))
            )
            args = ", ".join(f"$s{n}: String" for n in range(len(lote)))
            data = self._post(
                f"query({args}) {{ {aliases} }}",
                {f"s{n}": termo for n, termo in enumerate(lote)},
            )
            for n, termo in enumerate(lote):
                self.cache[termo] = data[f"a{n}"]["media"]
        if pendentes:
            self._save_cache()
        return {t: self.cache.get(t, []) for t in terms}

    def disponivel(self):
        """Sonda barata: a API de dados cai independente do resto do AniList."""
        try:
            self._post("{ Media(id: 1, type: ANIME) { id } }", {})
            log.info("API disponível (%s)", GRAPHQL)
            return True
        except (AniListError, requests.RequestException) as e:
            log.warning("API indisponível: %s", e)
            return False

    def _aguardar_vez(self):
        """Espaça as chamadas conforme o limite que a própria API informou."""
        atraso = self._proxima_chamada - time.monotonic()
        if atraso > 0:
            time.sleep(atraso)

    def _registrar_limite(self, resp):
        """Aprende o ritmo pelos headers: o limite muda (90/min normal, 30 degradado)."""
        try:
            self.limite = int(resp.headers["X-RateLimit-Limit"])
        except (KeyError, ValueError, TypeError):
            pass
        try:
            self.restante = int(resp.headers["X-RateLimit-Remaining"])
        except (KeyError, ValueError, TypeError):
            self.restante = None
        self._proxima_chamada = time.monotonic() + 60 / max(1, self.limite)

    def _espera_do_429(self, resp):
        """Segundos até poder tentar de novo, na ordem que a doc recomenda."""
        try:
            return max(1, int(resp.headers["Retry-After"]))
        except (KeyError, ValueError, TypeError):
            pass
        try:  # sem Retry-After, o reset vem como timestamp Unix
            return max(1, int(int(resp.headers["X-RateLimit-Reset"]) - time.time()))
        except (KeyError, ValueError, TypeError):
            return 60

    def _post(self, query, variables, tentativa=1):
        self._aguardar_vez()
        resp = self.session.post(
            GRAPHQL, json={"query": query, "variables": variables}, timeout=30
        )

        if resp.status_code == 429:
            espera = self._espera_do_429(resp)
            # limitado: sem teto, um 429 permanente prenderia a thread do servidor
            if tentativa >= MAX_TENTATIVAS:
                raise AniListError(
                    f"rate limit persistente após {tentativa} tentativas "
                    f"(aguardar {espera}s)"
                )
            log.warning("rate limit atingido; aguardando %ds (tentativa %d/%d)",
                        espera, tentativa, MAX_TENTATIVAS)
            time.sleep(espera)
            self._proxima_chamada = 0.0  # a espera do 429 já cobre o intervalo
            return self._post(query, variables, tentativa + 1)

        self._registrar_limite(resp)
        payload = resp.json() if resp.content else {}
        if not resp.ok or "errors" in payload:
            erro = (payload.get("errors") or [{}])[0].get("message", resp.text[:200])
            log.error("HTTP %s: %s", resp.status_code, erro)
            raise AniListError(f"AniList {resp.status_code}: {erro}")
        if self.restante is not None and self.restante <= max(2, self.limite // 10):
            log.warning("cota quase no fim: %d de %d restantes", self.restante, self.limite)
        return payload["data"]

    def _save_cache(self):
        with open(self.cache_path, "w") as fh:
            json.dump(self.cache, fh, ensure_ascii=False)


# --- matching (puro, testável sem rede) ---

ROMANOS = {"ii": "2", "iii": "3", "iv": "4", "v": "5", "vi": "6"}


def normalize(titulo):
    """Minúsculas, sem pontuação, com numeral romano virando dígito.

    Numerais viram dígitos porque a CR escreve 'Season 2' e o AniList 'II' —
    sem isso a temporada certa perde para a errada."""
    t = (titulo or "").casefold()
    t = re.sub(r"[^\w\s]", " ", t)
    palavras = [ROMANOS.get(p, p) for p in t.split()]
    palavras = [p for p in palavras if p not in ("season", "part", "the", "cour")]
    return " ".join(palavras)


def candidate_titles(media):
    titulos = media.get("title") or {}
    return [t for t in (*titulos.values(), *(media.get("synonyms") or [])) if t]


def score(query, media, episodes=0, years=None):
    """Similaridade de título ajustada por episódios e ano de exibição.

    Pode passar de 1.0 de propósito: com títulos idênticos (T1 vs T3 da mesma
    série) o texto satura e só os ajustes separam. O teto é aplicado depois,
    ao reportar a confiança."""
    if media.get("format") in IGNORED_FORMATS:
        return 0.0
    alvo = normalize(query)
    melhor = max(
        (difflib.SequenceMatcher(None, alvo, normalize(t)).ratio() for t in candidate_titles(media)),
        default=0.0,
    )
    if episodes and media.get("episodes") == episodes:
        melhor += 0.10
    ano = media.get("seasonYear")
    if years and ano:
        # fora da janela de exibição da temporada é quase certo ser outra cour
        melhor += 0.05 if years[0] <= ano <= years[1] else -0.25
    return melhor


def best_match(query, candidatos, episodes=0, years=None):
    """Melhor candidato acima do limiar, ou None. Devolve (media, score cru)."""
    ranking = sorted(
        ((c, score(query, c, episodes, years)) for c in candidatos),
        key=lambda par: par[1],
        reverse=True,
    )
    if ranking and min(1.0, ranking[0][1]) >= THRESHOLD:
        return ranking[0]
    return None


def season_queries(series_title, season):
    """Termos de busca para uma temporada, do mais específico ao mais genérico."""
    # a CR marca dublagem no título da temporada; o AniList não tem entrada separada
    titulo = re.sub(r"\((?:english|japanese)[^)]*\)", "", season.get("season_title") or "",
                    flags=re.I).strip()
    numero = season.get("season_number") or 0
    termos = []
    # "Season 2" não acrescenta nada à busca: vira só o dígito ao normalizar
    generico = not normalize(titulo) or normalize(titulo).isdigit()
    # o título da temporada às vezes já é o nome da obra no AniList
    if titulo and not generico and normalize(titulo) != normalize(series_title):
        termos.append(titulo if series_title.casefold() in titulo.casefold() else f"{series_title} {titulo}")
    if numero > 1:
        termos.append(f"{series_title} Season {numero}")
    termos.append(series_title)
    return list(dict.fromkeys(termos))


def match_seasons(client, series_title, seasons):
    """Casa cada temporada da CR com uma obra do AniList."""
    todos = [q for s in seasons for q in season_queries(series_title, s)]
    resultados = client.search_many(todos)

    saida = []
    for season in seasons:
        melhor = None
        for query in season_queries(series_title, season):
            achado = best_match(query, resultados.get(query, []),
                                season.get("total_episodes", 0), season.get("years"))
            if achado and (melhor is None or achado[1] > melhor[1]):
                melhor = achado
        media, conf = melhor if melhor else (None, 0.0)
        conf = min(1.0, conf)
        saida.append({
            # o id atravessa o matcher: season_number não é único por série
            # (uma série pode ter duas temporadas 0, OVAs e especiais)
            "season_id": season.get("season_id"),
            "season_number": season.get("season_number"),
            "season_title": season.get("season_title"),
            "cr_episodes": season.get("total_episodes"),
            "anilist_id": media["id"] if media else None,
            "anilist_title": (media["title"].get("romaji") if media else None),
            "anilist_episodes": media.get("episodes") if media else None,
            "anilist_url": media.get("siteUrl") if media else None,
            "confidence": round(conf, 3),
            # abaixo do limiar nada é gravado como certo; fica para revisão manual
            "needs_review": conf < 0.9,
        })
    return flag_duplicates(saida)


def flag_duplicates(seasons):
    """Duas temporadas da CR apontando para a mesma obra = uma delas está errada.

    Acontece quando a CR junta duas cours numa temporada só. Mantém a de maior
    confiança e manda a outra para revisão em vez de afirmar as duas."""
    melhor_por_id = {}
    for s in seasons:
        aid = s["anilist_id"]
        if aid is None:
            continue
        if aid not in melhor_por_id or s["confidence"] > melhor_por_id[aid]["confidence"]:
            melhor_por_id[aid] = s
    for s in seasons:
        aid = s["anilist_id"]
        if aid is not None and melhor_por_id[aid] is not s:
            s["needs_review"] = True
            s["duplicate_of"] = melhor_por_id[aid]["season_number"]
    return seasons
