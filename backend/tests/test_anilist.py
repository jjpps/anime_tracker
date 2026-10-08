"""Cache do AniList: acha, não acha e falha. Sem rede.

    python tests/test_anilist.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import anilist, db  # noqa: E402


def banco():
    conn = db.connect(":memory:")
    db.save_series(conn, [{"series_id": "S", "series_title": "S", "availability": "available",
                           "total_episodes": 0, "total_seasons": 0}])
    return conn


def test_acha_e_usa_o_cache():
    conn, chamadas = banco(), []

    def buscar(q, v):
        chamadas.append(v)
        return {"id": 7, "genres": ["Ação"]}

    assert anilist.detalhe(conn, "S", "S", buscar)["id"] == 7
    assert anilist.detalhe(conn, "S", "S", buscar)["genres"] == ["Ação"]
    assert len(chamadas) == 1 and db.get_anilist(conn, "S")["anilist_id"] == 7


def test_nao_achou_e_gravado_mas_falha_nao():
    conn, chamadas = banco(), []
    assert anilist.detalhe(conn, "S", "S", lambda q, v: chamadas.append(1)) is None
    anilist.detalhe(conn, "S", "S", lambda q, v: chamadas.append(1))
    assert len(chamadas) == 1

    conn = banco()

    def cai(q, v):
        raise anilist.AniListErro("fora")

    try:
        anilist.detalhe(conn, "S", "S", cai)
        assert False
    except anilist.AniListErro:
        pass
    assert db.get_anilist(conn, "S") is None


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
