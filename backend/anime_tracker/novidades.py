"""A regra do produto: o que saiu na CR dos animes que já comecei.

Os termos (temporada tocada, temporada nova, continuação, extra) estão
definidos no CONTEXT.md da raiz; aqui só está a conta.

Uma temporada é o número dela dentro do anime: as versões de áudio repetem o
número, então agrupar por ele junta dublado e legendado numa coisa só.
"""

import re
from collections import defaultdict
from datetime import datetime, timezone

# ponytail: a CR não marca o que é extra, então vai pelo título. Se errar
# demais, entra um botão "é extra / não é extra" por temporada.
EXTRA = re.compile(
    r"\b(movies?|films?|specials?|ovas?|oads?|extras?|compilations?|recaps?|re-edited)\b",
    re.I,
)


def e_extra(numero, titulos):
    """Número 0 é onde a CR guarda especiais; o resto, só se todas as versões
    tiverem cara de extra (JoJo "Re-Edited" é versão da temporada 1, não extra)."""
    return numero == 0 or all(EXTRA.search(t or "") for t in titulos)


def lista(conn):
    """Animes iniciados e não largados com pelo menos uma novidade, na ordem da tela."""
    temporadas = defaultdict(dict)  # series_id -> número -> {titulos, episodios}
    for r in conn.execute("SELECT series_id, season_number, title, total_episodes FROM seasons"):
        t = temporadas[r["series_id"]].setdefault(r["season_number"], {"titulos": [], "episodios": 0})
        t["titulos"].append(r["title"] or "")
        t["episodios"] = max(t["episodios"], r["total_episodes"] or 0)

    ultimo_ep = defaultdict(dict)  # series_id -> número -> último episódio visto nela
    for r in conn.execute(
        """SELECT series_id, season_number, MAX(episode_number) AS ep FROM watch_history
            WHERE season_number IS NOT NULL GROUP BY 1, 2"""
    ):
        ultimo_ep[r["series_id"]][r["season_number"]] = r["ep"]

    sessao = dict(conn.execute("SELECT series_id, MAX(watched_at) FROM watch_history GROUP BY 1"))
    series = {r["series_id"]: r for r in conn.execute("SELECT series_id, title, poster FROM series")}

    # quando cada número de episódio chegou pela primeira vez, em qualquer
    # versão de áudio: a dublagem de algo que eu já tinha deixado de lado não
    # é novidade
    lancado = defaultdict(list)  # (series_id, número) -> [(episódio, quando)]
    for r in conn.execute(
        """SELECT s.series_id, s.season_number, e.episode_number, MIN(e.released_at) AS quando
             FROM episodes e JOIN seasons s USING (season_id) GROUP BY 1, 2, 3"""
    ):
        lancado[(r["series_id"], r["season_number"])].append((r["episode_number"], r["quando"]))

    largados = {r[0] for r in conn.execute("SELECT series_id FROM dropped")}

    saida = []
    for series_id, vistos in ultimo_ep.items():
        if series_id in largados:
            continue
        principais = {n: t for n, t in temporadas.get(series_id, {}).items()
                      if not e_extra(n, t["titulos"])}
        tocadas = [n for n in vistos if n in principais]
        if not tocadas:
            continue
        ultima = max(tocadas)
        ultima_sessao = sessao.get(series_id)

        novas = [{"title": _titulo(principais[n]["titulos"]), "episodes": principais[n]["episodios"]}
                 for n in sorted(principais) if n > ultima and principais[n]["episodios"]]

        continuacao = None
        depois = [ep for ep, quando in lancado[(series_id, ultima)]
                  if ep > vistos[ultima] and _depois(quando, ultima_sessao)]
        if depois:
            continuacao = {"title": _titulo(principais[ultima]["titulos"]),
                           "episodes": len(depois)}

        if novas or continuacao:
            serie = series.get(series_id)
            saida.append({"series_id": series_id,
                          "title": (serie and serie["title"]) or series_id,
                          "poster": serie and serie["poster"],
                          "seasons_watched": len(tocadas), "last_watched_at": ultima_sessao,
                          "new_seasons": novas, "continuation": continuacao})

    # duas passadas com sort estável: recência desempata o número de temporadas
    saida.sort(key=lambda a: a["last_watched_at"] or "", reverse=True)
    saida.sort(key=lambda a: a["seasons_watched"], reverse=True)
    return saida


AUDIO = re.compile(r"\s*\([^)]*\b(dub|dublado)\b[^)]*\)", re.I)


def _titulo(titulos):
    """O nome da temporada sem o sufixo de áudio, preferindo a versão legendada."""
    return AUDIO.sub("", min(titulos, key=lambda t: (bool(AUDIO.search(t)), len(t))))


def _depois(a, b):
    """a > b entre datas ISO; sem data não dá para afirmar que saiu depois."""
    if not a or not b:
        return False
    return datetime.fromisoformat(a.replace("Z", "+00:00")) > datetime.fromisoformat(
        b.replace("Z", "+00:00"))


def pendentes(conn, series_id):
    """Episódios pendentes por Temporada principal, só as que têm algum.

    Dublado e legendado repetem o número do episódio: vale um só, preferindo
    o legendado. Episódio que ainda não chegou na CR não está disponível."""
    vistos = {(r["season_number"], r["episode_number"]) for r in conn.execute(
        """SELECT season_number, episode_number FROM watch_history
            WHERE series_id = ? AND fully_watched = 1""", [series_id])}
    agora = datetime.now(timezone.utc)

    por_numero = defaultdict(lambda: {"titulos": [], "eps": {}})
    for r in conn.execute(
        """SELECT s.season_number, s.title AS temporada, e.episode_number, e.episode_id,
                  e.title, e.released_at
             FROM episodes e JOIN seasons s USING (season_id) WHERE s.series_id = ?""",
        [series_id],
    ):
        if r["released_at"] and _depois(r["released_at"], agora.isoformat()):
            continue
        t = por_numero[r["season_number"]]
        t["titulos"].append(r["temporada"] or "")
        dub = bool(AUDIO.search(r["temporada"] or ""))
        atual = t["eps"].get(r["episode_number"])
        if atual is None or (atual["dub"] and not dub):
            t["eps"][r["episode_number"]] = {"number": r["episode_number"], "id": r["episode_id"],
                                             "title": r["title"], "dub": dub}

    saida = []
    for n in sorted(por_numero):
        t = por_numero[n]
        if e_extra(n, t["titulos"]):
            continue
        eps = [{k: v for k, v in e.items() if k != "dub"}
               for _, e in sorted(t["eps"].items()) if (n, e["number"]) not in vistos]
        if eps:
            saida.append({"title": _titulo(t["titulos"]), "episodes": eps})
    return saida
