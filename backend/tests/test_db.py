"""Checagem da persistência e das regras das cinco features. Sem rede.

    python tests/test_db.py
"""

import os
import sys

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db  # noqa: E402

SERIE = {
    "series_id": "G1", "series_title": "Mushoku Tensei", "availability": "available",
    "total_episodes": 60, "total_seasons": 3, "added_at": "2023-08-05T15:16:35Z",
    "is_favorite": False,
}
SEASONS = [
    {"season_id": "S1", "season_number": 1, "season_title": "Season 1",
     "total_episodes": 24, "years": (2021, 2022)},
    {"season_id": "S3", "season_number": 3, "season_title": "Season 3",
     "total_episodes": 11, "years": (2026, 2026)},
]
IDS = {1: "S1", 3: "S3"}


def novo_banco():
    conn = db.connect(":memory:")
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, SERIE["series_id"], SEASONS)
    return conn


def match(season_number, provider_id, title, conf, season_id=None,
          provider="anilist", duplicate_of=None):
    """Resultado do matcher: neutro de provedor, como sai de match_seasons."""
    return {"season_id": season_id or IDS.get(season_number),
            "season_number": season_number, "provider": provider,
            "provider_id": provider_id, "provider_title": title,
            "provider_episodes": 11, "provider_url": "", "provider_status": "FINISHED",
            "confidence": conf, "duplicate_of": duplicate_of}


# --- caminho do banco ---

def test_caminho_do_banco_ancora_na_raiz():
    """Rodar de outro diretório não pode criar um banco novo e vazio."""
    from anime_tracker.config import RAIZ

    anterior = os.environ.pop("ANIME_TRACKER_DB", None)
    try:
        os.environ["ANIME_TRACKER_DB"] = "anime_tracker.db"
        assert db.resolve_path() == os.path.join(RAIZ, "anime_tracker.db")
        assert db.resolve_path("/tmp/x.db") == "/tmp/x.db"
        assert db.resolve_path(":memory:") == ":memory:"
        # caminho com separador é do cwd: ancorar na raiz criaria banco perdido
        assert db.resolve_path("../x.db") == "../x.db"
        assert db.resolve_path("dados/x.db") == "dados/x.db"
    finally:
        os.environ.pop("ANIME_TRACKER_DB", None)
        if anterior is not None:
            os.environ["ANIME_TRACKER_DB"] = anterior


# --- 1. dados da Crunchyroll ---

def test_grava_series_e_temporadas():
    conn = novo_banco()
    assert db.stats(conn)["series"] == 1
    linhas = conn.execute("SELECT * FROM seasons ORDER BY season_number").fetchall()
    assert [r["season_number"] for r in linhas] == [1, 3]
    assert linhas[1]["year_start"] == 2026  # a faixa de anos precisa sobreviver


def test_importar_de_novo_e_idempotente():
    conn = novo_banco()
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, SERIE["series_id"], SEASONS)
    s = db.stats(conn)
    assert (s["series"], s["seasons"]) == (1, 2)


# --- 2. match e a regra do 1.00 ---

def test_confianca_total_vira_match_ok():
    """Regra: 1.00 é match resolvido; abaixo disso vai para pendentes."""
    conn = novo_banco()
    db.save_matches(conn, [match(1, 108465, "Mushoku", 1.0),
                           match(3, 166873, "Mushoku III", 0.99)])
    por_id = {r["season_id"]: r["review_status"]
              for r in conn.execute("SELECT season_id, review_status FROM matches")}
    assert por_id == {"S1": "confirmed", "S3": "pending"}


def test_duplicata_nao_vira_match_ok_nem_em_1():
    """Duas temporadas na mesma obra é o caso ambíguo, por mais parecido que seja."""
    conn = novo_banco()
    db.save_matches(conn, [match(1, 21, "One Piece", 1.0),
                           match(3, 21, "One Piece", 1.0, duplicate_of=1)])
    por_id = {r["season_id"]: r["review_status"]
              for r in conn.execute("SELECT season_id, review_status FROM matches")}
    assert por_id == {"S1": "confirmed", "S3": "pending"}


def test_match_ok():
    assert db.match_ok(match(1, 1, "a", 1.0)) is True
    assert db.match_ok(match(1, 1, "a", 0.999)) is False
    assert db.match_ok(match(1, None, None, 1.0)) is False
    assert db.match_ok(match(1, 1, "a", 1.0, duplicate_of=2)) is False


def test_decisao_humana_sobrevive_a_novo_match():
    """Rodar o matcher de novo não pode desfazer o que a pessoa decidiu."""
    conn = novo_banco()
    db.save_matches(conn, [match(3, 108465, "errado", 0.8)])
    db.vincular(conn, "S3", "anilist", 999)

    db.save_matches(conn, [match(3, 108465, "errado de novo", 0.8)])
    linha = conn.execute("SELECT * FROM matches WHERE season_id='S3'").fetchone()
    assert linha["anilist_id"] == 999 and linha["review_status"] == "confirmed"


def test_pendente_e_atualizado_por_novo_match():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 1, "primeiro", 0.8)])
    db.save_matches(conn, [match(1, 2, "segundo", 0.95)])
    linha = conn.execute("SELECT * FROM matches WHERE season_id='S1'").fetchone()
    assert linha["anilist_id"] == 2, "pendente deveria aceitar o match novo"


def test_provedores_sao_independentes():
    """Casar no MyAnimeList não pode apagar o vínculo do AniList.

    E o inverso: um match 1.00 no AniList confirma a linha, mas isso não pode
    travá-la — o MyAnimeList ainda precisa conseguir gravar o id dele."""
    conn = novo_banco()
    db.save_matches(conn, [match(1, 108465, "A", 1.0, provider="anilist")])
    db.save_matches(conn, [match(1, 39535, "M", 1.0, provider="mal")])
    linha = conn.execute("SELECT anilist_id, mal_id FROM matches").fetchone()
    assert (linha["anilist_id"], linha["mal_id"]) == (108465, 39535)


def test_segundo_provedor_nao_rebaixa_o_confirmado():
    """Match fraco no MAL não pode devolver à fila algo já resolvido."""
    conn = novo_banco()
    db.save_matches(conn, [match(1, 108465, "A", 1.0, provider="anilist")])
    db.save_matches(conn, [match(1, 39535, "M", 0.5, provider="mal")])
    linha = conn.execute("SELECT review_status, mal_id FROM matches").fetchone()
    assert linha["review_status"] == "confirmed" and linha["mal_id"] == 39535


def test_vinculo_existente_nao_e_sobrescrito_por_rematch():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 108465, "A", 1.0, provider="anilist")])
    db.save_matches(conn, [match(1, 999, "outro", 1.0, provider="anilist")])
    linha = conn.execute("SELECT anilist_id FROM matches").fetchone()
    assert linha["anilist_id"] == 108465, "match confirmado foi sobrescrito"


def test_provider_invalido_recusado():
    conn = novo_banco()
    try:
        db.save_matches(conn, [match(1, 1, "a", 1.0, provider="kitsu")])
        raise AssertionError("deveria recusar")
    except ValueError:
        pass


def test_temporada_sem_id_e_ignorada():
    conn = novo_banco()
    assert db.save_matches(conn, [match(99, 1, "a", 0.8, season_id=None)]) == 0


def test_duas_temporadas_com_mesmo_numero():
    """Konosuba tem duas temporadas 0 (OVAs e especiais): as duas têm que caber."""
    conn = db.connect(":memory:")
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, "G1", [
        {"season_id": "OVA1", "season_number": 0, "season_title": "OVAs",
         "total_episodes": 2, "years": (2017, 2017)},
        {"season_id": "OVA2", "season_number": 0, "season_title": "Legend of Crimson",
         "total_episodes": 1, "years": (2019, 2019)},
    ])
    n = db.save_matches(conn, [match(0, 10, "a", 0.9, season_id="OVA1"),
                               match(0, 20, "b", 0.9, season_id="OVA2")])
    assert n == 2 and db.stats(conn)["matched"] == 2


# --- 3 e 4. biblioteca e pendentes ---

def test_biblioteca_e_pendentes_se_separam():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 108465, "Mushoku", 1.0),
                           match(3, 166873, "Mushoku III", 0.8)])
    assert [r["season_id"] for r in db.biblioteca(conn)] == ["S1"]
    assert [r["season_id"] for r in db.pendentes(conn)] == ["S3"]


def test_biblioteca_traz_o_rotulo_do_provedor():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 108465, "A", 1.0, provider="anilist")])
    assert db.biblioteca(conn)[0]["providers"] == "anilist"

    db.vincular(conn, "S1", "mal", 39535)
    assert db.biblioteca(conn)[0]["providers"] == "anilist,mal"


def test_pendente_com_id_de_baixa_confianca_aparece():
    """Filtrar por "id ausente" esconderia o que mais precisa de correção."""
    conn = novo_banco()
    db.save_matches(conn, [match(1, 108465, "A", 1.0), match(3, 1, "B", 0.5)])
    pend = db.pendentes(conn)
    assert [r["season_id"] for r in pend] == ["S3"]
    assert pend[0]["anilist_id"] == 1, "tem id, mas a confiança é baixa"


def test_rejeitado_sai_das_duas_listas():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 1, "a", 0.5)])
    db.set_review(conn, "S1", "rejected")
    assert db.biblioteca(conn) == [] and db.pendentes(conn) == []


# --- 5. vínculo manual ---

def test_vincular_confirma_o_match():
    """Quem digitou o id já decidiu: entra como resolvido."""
    conn = novo_banco()
    db.save_matches(conn, [match(1, None, None, 0.0)])
    assert db.vincular(conn, "S1", "mal", 39535, "Mushoku Tensei") == 1

    item = db.biblioteca(conn)[0]
    assert item["mal_id"] == 39535 and item["mal_title"] == "Mushoku Tensei"
    assert item["review_status"] == "confirmed" and item["providers"] == "mal"
    assert db.pendentes(conn) == []


def test_vincular_temporada_inexistente():
    conn = novo_banco()
    assert db.vincular(conn, "NAOEXISTE", "mal", 1) == 0


def test_vincular_provider_invalido():
    conn = novo_banco()
    try:
        db.vincular(conn, "S1", "kitsu", 1)
        raise AssertionError("deveria recusar")
    except ValueError:
        pass


def test_stats():
    conn = novo_banco()
    db.save_matches(conn, [match(1, 1, "a", 1.0), match(3, 2, "b", 0.5)])
    s = db.stats(conn)
    assert (s["confirmed"], s["pending"], s["com_anilist"]) == (1, 1, 2)


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
