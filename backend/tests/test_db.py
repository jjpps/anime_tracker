"""Checagem da persistência. Banco em memória, sem rede.

    python tests/test_db.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db  # noqa: E402

SERIE = {
    "series_id": "G24H1N3MP", "series_title": "Mushoku Tensei", "availability": "available",
    "total_episodes": 60, "total_seasons": 3, "added_at": "2023-08-05T15:16:35Z",
    "is_favorite": False,
}
SEASONS = [
    {"season_id": "S1", "season_number": 1, "season_title": "Season 1",
     "total_episodes": 24, "years": (2021, 2022)},
    {"season_id": "S3", "season_number": 3, "season_title": "Season 3",
     "total_episodes": 11, "years": (2026, 2026)},
]


def novo_banco():
    conn = db.connect(":memory:")
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, SERIE["series_id"], SEASONS)
    return conn


def match(season_number, anilist_id, title, conf):
    return {"season_number": season_number, "anilist_id": anilist_id, "anilist_title": title,
            "anilist_episodes": 11, "anilist_url": "", "confidence": conf}


IDS = {1: "S1", 3: "S3"}


def test_grava_series_e_temporadas():
    conn = novo_banco()
    assert db.stats(conn)["series"] == 1
    linhas = db.seasons_of(conn, "G24H1N3MP")
    assert [r["season_number"] for r in linhas] == [1, 3]
    assert linhas[1]["year_start"] == 2026  # a faixa de anos precisa sobreviver


def test_sync_e_idempotente():
    conn = novo_banco()
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, SERIE["series_id"], SEASONS)
    s = db.stats(conn)
    assert (s["series"], s["seasons"]) == (1, 2)


def test_revisao_sobrevive_a_novo_match():
    """O ponto central: rodar o matcher de novo não desfaz decisão humana."""
    conn = novo_banco()
    db.save_matches(conn, IDS, "G24H1N3MP", [match(3, 108465, "errado", 1.0)])
    db.set_review(conn, "S3", "confirmed", anilist_id=999)

    # matcher roda de novo e insiste no id errado
    db.save_matches(conn, IDS, "G24H1N3MP", [match(3, 108465, "errado de novo", 1.0)])

    linha = conn.execute("SELECT * FROM matches WHERE season_id='S3'").fetchone()
    assert linha["anilist_id"] == 999, "match revisado foi sobrescrito"
    assert linha["review_status"] == "confirmed"
    assert linha["anilist_title"] == "errado", "título revisado foi sobrescrito"


def test_pendente_e_atualizado_por_novo_match():
    conn = novo_banco()
    db.save_matches(conn, IDS, "G24H1N3MP", [match(1, 1, "primeiro", 0.8)])
    db.save_matches(conn, IDS, "G24H1N3MP", [match(1, 2, "segundo", 0.95)])
    linha = conn.execute("SELECT * FROM matches WHERE season_id='S1'").fetchone()
    assert linha["anilist_id"] == 2, "pendente deveria aceitar o match novo"


def test_separa_revisados_de_pendentes():
    conn = novo_banco()
    db.save_matches(conn, IDS, "G24H1N3MP",
                    [match(1, 1, "a", 0.8), match(3, 3, "b", 0.9)])
    db.set_review(conn, "S1", "confirmed")

    pendentes = db.pending_review(conn)
    revisados = db.reviewed(conn)
    assert [r["season_id"] for r in pendentes] == ["S3"]
    assert [r["season_id"] for r in revisados] == ["S1"]
    assert revisados[0]["reviewed_at"] is not None
    assert revisados[0]["series_title"] == "Mushoku Tensei"

    s = db.stats(conn)
    assert (s["pending"], s["confirmed"], s["rejected"]) == (1, 1, 0)


def test_rejeitado_conta_como_revisado():
    conn = novo_banco()
    db.save_matches(conn, IDS, "G24H1N3MP", [match(1, 1, "a", 0.8)])
    db.set_review(conn, "S1", "rejected")
    assert db.stats(conn)["rejected"] == 1
    assert db.pending_review(conn) == []


def test_status_invalido_recusado():
    conn = novo_banco()
    db.save_matches(conn, IDS, "G24H1N3MP", [match(1, 1, "a", 0.8)])
    try:
        db.set_review(conn, "S1", "talvez")
        raise AssertionError("deveria recusar status inválido")
    except ValueError:
        pass


def test_temporada_inexistente_e_ignorada():
    conn = novo_banco()
    # o matcher pode devolver temporada que não está no banco; não pode estourar
    assert db.save_matches(conn, IDS, "G24H1N3MP", [match(99, 1, "a", 0.8)]) == 0


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
