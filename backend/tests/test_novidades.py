"""Checagem da regra de novidades (termos no CONTEXT.md). Sem rede.

Os cenários vêm do banco real: a CR numera extras na mesma sequência das
temporadas e anexa a parte seguinte na mesma temporada.

    python tests/test_novidades.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db, novidades  # noqa: E402

ANTES = "2025-01-01T00:00:00Z"
SESSAO = "2025-09-29T00:00:00Z"
DEPOIS = "2026-04-01T00:00:00Z"


def temporada(season_id, numero, titulo, eps, quando=ANTES, primeiro=1):
    return {"season_id": season_id, "season_number": numero, "season_title": titulo,
            "total_episodes": eps,
            "episodes": [{"episode_number": float(n), "released_at": quando}
                         for n in range(primeiro, primeiro + eps)]}


def banco(series_id, titulo, temporadas, vistos):
    """vistos: [(temporada, episódio, quando)]"""
    conn = db.connect(":memory:")
    db.save_series(conn, [{"series_id": series_id, "series_title": titulo,
                           "availability": "available", "total_episodes": 0,
                           "total_seasons": 0}])
    db.save_seasons(conn, series_id, temporadas)
    db.save_history(conn, [
        {"episode_id": f"{series_id}-{t}-{e}", "series_id": series_id, "series_title": titulo,
         "season_number": t, "episode_number": float(e), "episode_title": "",
         "watched_at": q, "fully_watched": True}
        for t, e, q in vistos])
    return conn


def test_temporada_nova_depois_da_ultima_tocada():
    """O exemplo do CONTEXT: vi o ep. 1 da temporada 3 e a 4 já existe."""
    conn = banco("DS", "Dr. STONE", [
        temporada("a", 1, "Dr. STONE", 24),
        temporada("b", 3, "Dr. STONE Season 3", 22),
        temporada("c", 4, "Dr. STONE Season 4", 12),
    ], [(3, 1, SESSAO)])
    [a] = novidades.lista(conn)
    assert [t["title"] for t in a["new_seasons"]] == ["Dr. STONE Season 4"]
    # parar no ep. 1 de uma temporada já lançada não é continuação
    assert a["continuation"] is None


def test_temporadas_anteriores_contam_como_vistas():
    conn = banco("X", "X", [temporada("a", 1, "S1", 12), temporada("b", 2, "S2", 12)],
                 [(2, 12, SESSAO)])
    assert novidades.lista(conn) == []


def test_continuacao_anexada_na_mesma_temporada():
    """SCIENCE FUTURE: vi 1-24, a CR anexou 25-37 depois."""
    antigos = temporada("sf", 5, "Dr. STONE SCIENCE FUTURE", 24)
    novos = temporada("sf", 5, "", 13, quando=DEPOIS, primeiro=25)["episodes"]
    antigos["episodes"] += novos
    antigos["total_episodes"] = 37
    conn = banco("DS", "Dr. STONE", [antigos], [(5, e, SESSAO) for e in range(1, 25)])
    [a] = novidades.lista(conn)
    assert a["continuation"] == {"title": "Dr. STONE SCIENCE FUTURE", "episodes": 13}
    assert a["new_seasons"] == []


def test_extra_nao_e_novidade_nem_ultima_tocada():
    """O ep. de "Extras" (#6) não pode esconder a continuação da #5."""
    conn = banco("DS", "Dr. STONE", [
        temporada("b", 4, "Dr. STONE Season 3", 22),
        temporada("x", 6, "Extras", 1, quando=DEPOIS),
        temporada("m", 7, "Dr. STONE The Movie", 1, quando=DEPOIS),
        temporada("c", 8, "Dr. STONE Season 4", 12, quando=DEPOIS),
    ], [(4, 22, SESSAO), (6, 1, SESSAO)])
    [a] = novidades.lista(conn)
    assert [t["title"] for t in a["new_seasons"]] == ["Dr. STONE Season 4"]


def test_so_extra_assistido_nao_inicia_o_anime():
    conn = banco("K", "Konosuba", [temporada("o", 0, "OVAs", 2), temporada("a", 1, "S1", 10)],
                 [(0, 1, SESSAO)])
    assert novidades.lista(conn) == []


def test_dublagem_e_a_mesma_temporada():
    """Dublado lançado depois de eu parar no meio não é continuação nem temporada."""
    conn = banco("DM", "Demon Slayer", [
        temporada("leg", 6, "Swordsmith Village Arc", 11),
        temporada("dub", 6, "Swordsmith Village Arc (English Dub)", 11, quando=DEPOIS),
    ], [(6, 5, SESSAO)])
    assert novidades.lista(conn) == []


def test_versao_com_mesmo_numero_nao_e_extra():
    """JoJo "Re-Edited" divide o número com a temporada 1: a 1 continua principal."""
    assert not novidades.e_extra(1, ["JoJo's Bizarre Adventure",
                                     "JoJo's Bizarre Adventure Re-Edited"])
    assert novidades.e_extra(3, ["Demon Slayer: Kimetsu no Yaiba TV Specials"])
    assert novidades.e_extra(2, ["Demon Slayer -Kimetsu no Yaiba- The Movie: Mugen Train"])
    assert novidades.e_extra(0, ["Qualquer coisa"])


def test_titulo_sem_sufixo_de_audio():
    assert novidades._titulo(["In/Spectre 2 (English Dub)"]) == "In/Spectre 2"
    assert novidades._titulo(["Arc (Portuguese Dub)", "Arc"]) == "Arc"


def test_temporada_anunciada_sem_episodio_nao_aparece():
    conn = banco("X", "X", [temporada("a", 1, "S1", 12), temporada("b", 2, "S2", 0)],
                 [(1, 12, SESSAO)])
    assert novidades.lista(conn) == []


def test_ordem_temporadas_tocadas_e_depois_recencia():
    conn = db.connect(":memory:")
    for sid, tocadas, quando in [("A", 1, "2026-01-01T00:00:00Z"),
                                 ("B", 2, "2024-01-01T00:00:00Z"),
                                 ("C", 1, "2026-06-01T00:00:00Z")]:
        db.save_series(conn, [{"series_id": sid, "series_title": sid, "availability": "available",
                               "total_episodes": 0, "total_seasons": 0}])
        db.save_seasons(conn, sid, [temporada(f"{sid}{n}", n, f"S{n}", 12)
                                    for n in range(1, tocadas + 2)])
        db.save_history(conn, [
            {"episode_id": f"{sid}{n}", "series_id": sid, "series_title": sid,
             "season_number": n, "episode_number": 12.0, "episode_title": "",
             "watched_at": quando, "fully_watched": True} for n in range(1, tocadas + 1)])
    assert [a["series_id"] for a in novidades.lista(conn)] == ["B", "C", "A"]


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
