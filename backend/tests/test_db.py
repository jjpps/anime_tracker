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


def match(season_number, provider_id, title, conf, season_id=None, provider="anilist"):
    """Resultado do matcher: neutro de provedor, como sai de match_seasons."""
    return {"season_id": season_id or IDS.get(season_number),
            "season_number": season_number, "provider": provider,
            "provider_id": provider_id, "provider_title": title,
            "provider_episodes": 11, "provider_url": "", "provider_status": "FINISHED",
            "confidence": conf}


IDS = {1: "S1", 3: "S3"}


def test_caminho_do_banco_ancora_na_raiz():
    """Rodar de outro diretório não pode criar um banco novo e vazio."""
    from anime_tracker.config import RAIZ

    anterior = os.environ.get("ANIME_TRACKER_DB")
    os.environ["ANIME_TRACKER_DB"] = "anime_tracker.db"
    try:
        assert db.resolve_path() == os.path.join(RAIZ, "anime_tracker.db")
        assert db.resolve_path("/tmp/x.db") == "/tmp/x.db"   # absoluto passa direto
        assert db.resolve_path(":memory:") == ":memory:"
        # caminho com separador é do cwd: ancorar na raiz criaria banco perdido
        assert db.resolve_path("../x.db") == "../x.db"
        assert db.resolve_path("dados/x.db") == "dados/x.db"
    finally:
        os.environ.pop("ANIME_TRACKER_DB", None)
        if anterior is not None:
            os.environ["ANIME_TRACKER_DB"] = anterior


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
    db.save_matches(conn, [match(3, 108465, "errado", 1.0)])
    db.set_review(conn, "S3", "confirmed", anilist_id=999)

    # matcher roda de novo e insiste no id errado
    db.save_matches(conn, [match(3, 108465, "errado de novo", 1.0)])

    linha = conn.execute("SELECT * FROM matches WHERE season_id='S3'").fetchone()
    assert linha["anilist_id"] == 999, "match revisado foi sobrescrito"
    assert linha["review_status"] == "confirmed"
    assert linha["anilist_title"] == "errado", "título revisado foi sobrescrito"


def test_pendente_e_atualizado_por_novo_match():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 1, "primeiro", 0.8)])
    db.save_matches(conn, [match(1, 2, "segundo", 0.95)])
    linha = conn.execute("SELECT * FROM matches WHERE season_id='S1'").fetchone()
    assert linha["anilist_id"] == 2, "pendente deveria aceitar o match novo"


def test_separa_revisados_de_pendentes():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 1, "a", 0.8), match(3, 3, "b", 0.9)])
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
    db.save_matches(conn, [match(1, 1, "a", 0.8)])
    db.set_review(conn, "S1", "rejected")
    assert db.stats(conn)["rejected"] == 1
    assert db.pending_review(conn) == []


def test_status_invalido_recusado():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 1, "a", 0.8)])
    try:
        db.set_review(conn, "S1", "talvez")
        raise AssertionError("deveria recusar status inválido")
    except ValueError:
        pass


def test_temporada_sem_id_e_ignorada():
    conn = novo_banco()
    # o matcher pode devolver temporada sem id; não pode estourar
    assert db.save_matches(conn, [match(99, 1, "a", 0.8)]) == 0


def test_duas_temporadas_com_mesmo_numero():
    """Konosuba tem duas temporadas 0 (OVAs e especiais): as duas têm que caber."""
    conn = db.connect(":memory:")
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, SERIE["series_id"], [
        {"season_id": "OVA1", "season_number": 0, "season_title": "OVAs",
         "total_episodes": 2, "years": (2017, 2017)},
        {"season_id": "OVA2", "season_number": 0, "season_title": "Legend of Crimson",
         "total_episodes": 1, "years": (2019, 2019)},
    ])
    n = db.save_matches(conn, [match(0, 10, "a", 0.9, season_id="OVA1"),
                               match(0, 20, "b", 0.9, season_id="OVA2")])
    assert n == 2
    assert db.stats(conn)["matched"] == 2


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
