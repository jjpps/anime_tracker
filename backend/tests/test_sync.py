"""Checagem da regra de sync incremental. Cliente falso, sem rede.

    python tests/test_sync.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db, sync  # noqa: E402


class CRFalso:
    """Conta chamadas: o ponto do incremental é não pagar o caro à toa."""

    def __init__(self, historico=None, watchlist=None, objetos=None, temporadas=None):
        self._historico = historico or []
        self._watchlist = watchlist or []
        self._objetos = objetos or {}
        self._temporadas = temporadas or {}
        self.since_recebido = "NAO_CHAMADO"
        self.series_com_temporadas_buscadas = []

    def watch_history(self, since=None, **kw):
        self.since_recebido = since
        # o cliente real corta pela data; aqui reproduzimos isso
        return [e for e in self._historico if not since or (e["watched_at"] or "") >= since]

    def watchlist(self, **kw):
        return list(self._watchlist)

    def resolve_objects(self, ids, **kw):
        return {i: self._objetos[i] for i in ids if i in self._objetos}

    def seasons(self, series_id, **kw):
        self.series_com_temporadas_buscadas.append(series_id)
        return self._temporadas.get(series_id, [])


def objeto(titulo, eps, temps, disponivel=True):
    return {
        "title": titulo,
        "series_metadata": {
            "episode_count": eps, "season_count": temps,
            "availability_status": "available" if disponivel else "unavailable",
        },
    }


def episodio(episode_id, series_id, quando, numero=1.0):
    return {"episode_id": episode_id, "series_id": series_id, "series_title": "S",
            "season_number": 1, "episode_number": numero, "episode_title": "e",
            "watched_at": quando, "fully_watched": True}


def entrada(series_id):
    return {"series_id": series_id, "series_title": "S", "availability": "available",
            "total_episodes": 0, "total_seasons": 0, "added_at": "2024-01-01T00:00:00Z",
            "is_favorite": False}


TEMPORADAS = {"A": [{"season_id": "A1", "season_number": 1, "season_title": "S1",
                     "total_episodes": 12, "years": (2024, 2024)}]}


def cr_padrao(**kw):
    base = dict(
        historico=[episodio("e1", "A", "2026-01-10T00:00:00Z")],
        watchlist=[entrada("A")],
        objetos={"A": objeto("Serie A", 12, 1)},
        temporadas=TEMPORADAS,
    )
    base.update(kw)
    return CRFalso(**base)


class MatcherFalso:
    """Devolve sempre um candidato, para o sync ter o que gravar."""

    def __init__(self):
        self.buscas = 0

    def search_many(self, terms):
        self.buscas += len(terms)
        return {t: [{"id": 42, "title": {"romaji": t, "english": None, "native": None},
                     "synonyms": [], "format": "TV", "episodes": 12,
                     "seasonYear": 2024, "siteUrl": "https://anilist.co/anime/42"}]
                for t in terms}


def test_sync_casa_e_grava_match():
    conn = db.connect(":memory:")
    m = MatcherFalso()
    r = sync.run(cr_padrao(), conn, force=True, matcher=m)

    assert r["matches"] == 1, "o sync tem que gravar match"
    assert m.buscas > 0
    # o MatcherFalso devolve título diferente do da série, então a confiança
    # não fecha em 1.00 e a temporada cai em pendentes
    assert len(db.pendentes(conn)) + len(db.biblioteca(conn)) == 1


def test_segundo_sync_nao_recasa_o_que_ja_tem_match():
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=MatcherFalso())

    m = MatcherFalso()
    r = sync.run(cr_padrao(), conn, force=True, matcher=m)
    assert m.buscas == 0, "recasou temporada que já tinha match"
    assert r["matches"] == 0


def test_sync_nao_desfaz_revisao():
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=MatcherFalso())
    db.vincular(conn, "A1", "anilist", 999)

    # temporada nova na série força recasar tudo dela
    sync.run(cr_padrao(objetos={"A": objeto("Serie A", 13, 1)}), conn,
             force=True, matcher=MatcherFalso())
    linha = conn.execute("SELECT * FROM matches WHERE season_id='A1'").fetchone()
    assert linha["anilist_id"] == 999 and linha["review_status"] == "confirmed"


def test_sem_fonte_de_match_o_sync_ainda_completa():
    """AniList fora e sem catálogo local: sincroniza e avisa, não quebra."""
    conn = db.connect(":memory:")
    r = sync.run(cr_padrao(), conn, force=True, matcher=None)
    assert r["series"] == 1 and r["episodios"] == 1
    assert r["matches"] == 0


def test_primeiro_sync_e_completo():
    conn = db.connect(":memory:")
    cr = cr_padrao()
    r = sync.run(cr, conn, force=True, matcher=None)

    assert r["incremental"] is False
    assert cr.since_recebido is None, "primeiro sync não pode limitar por data"
    assert r["episodios"] == 1 and r["series"] == 1
    assert cr.series_com_temporadas_buscadas == ["A"]


def test_segundo_sync_nao_rebusca_temporadas():
    """Contagem igual = nada mudou = não paga a parte cara."""
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=None)

    cr = cr_padrao()
    r = sync.run(cr, conn, force=True, matcher=None)
    assert cr.series_com_temporadas_buscadas == [], "rebuscou temporada sem motivo"
    assert r["series_atualizadas"] == 0


def test_episodio_novo_dispara_rebusca():
    """episode_count sobe quando estreia episódio: é o detector de mudança."""
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=None)

    cr = cr_padrao(objetos={"A": objeto("Serie A", 13, 1)})
    r = sync.run(cr, conn, force=True, matcher=None)
    assert cr.series_com_temporadas_buscadas == ["A"]
    assert r["series_atualizadas"] == 1


def test_temporada_nova_dispara_rebusca():
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=None)

    cr = cr_padrao(objetos={"A": objeto("Serie A", 12, 2)})
    sync.run(cr, conn, force=True, matcher=None)
    assert cr.series_com_temporadas_buscadas == ["A"]


def test_historico_incremental_usa_marca_dagua():
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=None)

    cr = cr_padrao()
    sync.run(cr, conn, force=True, matcher=None)
    assert cr.since_recebido is not None, "segundo sync deveria cortar por data"
    # a folga de 1 dia recua a marca em relação ao episódio mais recente
    assert cr.since_recebido < "2026-01-10T00:00:00Z"
    assert cr.since_recebido > "2026-01-08T00:00:00Z"


def test_escopo_inclui_serie_so_do_historico():
    """42 séries assistidas não estão na watchlist; elas precisam entrar."""
    conn = db.connect(":memory:")
    cr = CRFalso(
        historico=[episodio("e1", "A", "2026-01-10T00:00:00Z"),
                   episodio("e2", "B", "2026-01-09T00:00:00Z")],
        watchlist=[entrada("A")],
        objetos={"A": objeto("Serie A", 12, 1), "B": objeto("Serie B", 24, 2)},
        temporadas=TEMPORADAS,
    )
    sync.run(cr, conn, force=True, matcher=None)

    linhas = {r["series_id"]: r for r in conn.execute("SELECT * FROM series")}
    assert set(linhas) == {"A", "B"}
    assert linhas["A"]["in_watchlist"] == 1
    assert linhas["B"]["in_watchlist"] == 0, "série só do histórico deve ficar marcada"
    assert sorted(cr.series_com_temporadas_buscadas) == ["A", "B"]


def test_serie_indisponivel_nao_gasta_chamada():
    conn = db.connect(":memory:")
    cr = cr_padrao(objetos={"A": objeto("Serie A", 0, 0, disponivel=False)})
    sync.run(cr, conn, force=True, matcher=None)
    assert cr.series_com_temporadas_buscadas == []


def test_titulo_vem_do_historico_quando_cms_nao_resolve():
    """Séries removidas do catálogo dão 404; o nome ainda está no histórico."""
    conn = db.connect(":memory:")
    cr = CRFalso(historico=[episodio("e1", "Z", "2026-01-10T00:00:00Z")],
                 watchlist=[], objetos={}, temporadas={})
    sync.run(cr, conn, force=True, matcher=None)
    linha = conn.execute("SELECT title FROM series WHERE series_id='Z'").fetchone()
    assert linha["title"] == "S"


def test_ttl_bloqueia_e_force_atravessa():
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=None)

    try:
        sync.run(cr_padrao(), conn, ttl_horas=6, matcher=None)
        raise AssertionError("deveria bloquear dentro do TTL")
    except sync.SyncBloqueado as e:
        assert 0 < e.minutos_restantes <= 6 * 60

    sync.run(cr_padrao(), conn, force=True, matcher=None)  # force ignora o TTL
    assert sync.minutos_ate_liberar(conn, ttl_horas=0) == 0


def test_ttl_zero_nao_bloqueia():
    conn = db.connect(":memory:")
    sync.run(cr_padrao(), conn, force=True, matcher=None)
    sync.run(cr_padrao(), conn, ttl_horas=0, matcher=None)


def test_precisa_temporadas():
    novo = {"total_episodes": 12, "total_seasons": 1}
    assert sync.precisa_temporadas(novo, None) is True
    assert sync.precisa_temporadas(novo, {"tem_temporadas": 0, "total_episodes": 12,
                                          "total_seasons": 1}) is True
    assert sync.precisa_temporadas(novo, {"tem_temporadas": 1, "total_episodes": 12,
                                          "total_seasons": 1}) is False
    assert sync.precisa_temporadas(novo, {"tem_temporadas": 1, "total_episodes": 11,
                                          "total_seasons": 1}) is True


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
