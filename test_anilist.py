"""Checagem do matcher CR -> AniList. Sem rede: candidatos são fixtures.

    python test_anilist.py
"""

from anilist import best_match, normalize, score, season_queries

MUSHOKU_T1 = {
    "id": 108465, "format": "TV", "episodes": 11, "seasonYear": 2021,
    "title": {"romaji": "Mushoku Tensei: Isekai Ittara Honki Dasu",
              "english": "Mushoku Tensei: Jobless Reincarnation", "native": "無職転生"},
    "synonyms": ["Mushoku Tensei Season 1"], "siteUrl": "https://anilist.co/anime/108465",
}
MUSHOKU_T2 = {
    "id": 146065, "format": "TV", "episodes": 12, "seasonYear": 2023,
    "title": {"romaji": "Mushoku Tensei II: Isekai Ittara Honki Dasu",
              "english": "Mushoku Tensei: Jobless Reincarnation Season 2", "native": "無職転生II"},
    "synonyms": [], "siteUrl": "https://anilist.co/anime/146065",
}
TRILHA = {
    "id": 999, "format": "MUSIC", "episodes": 1, "seasonYear": 2021,
    "title": {"romaji": "Mushoku Tensei Opening", "english": None, "native": None},
    "synonyms": [], "siteUrl": "",
}
CANDIDATOS = [MUSHOKU_T1, MUSHOKU_T2, TRILHA]


def test_normalize():
    assert normalize("Mushoku Tensei II") == normalize("Mushoku Tensei 2")
    assert normalize("Attack on Titan: Season 3") == "attack on titan 3"
    assert normalize(None) == ""


def test_formato_ignorado():
    # trilha sonora nunca deve casar, por mais parecido que seja o título
    assert score("Mushoku Tensei Opening", TRILHA) == 0.0


def test_escolhe_temporada_certa():
    m, conf = best_match("Mushoku Tensei: Jobless Reincarnation Season 2", CANDIDATOS)
    assert m["id"] == MUSHOKU_T2["id"], f"casou errado: {m['title']['romaji']}"
    assert conf >= 0.9

    m, _ = best_match("Mushoku Tensei: Jobless Reincarnation", CANDIDATOS)
    assert m["id"] == MUSHOKU_T1["id"]


def test_episodios_desempatam():
    # mesmo título nos dois; só a contagem de episódios separa
    a = {**MUSHOKU_T1, "id": 1, "episodes": 11, "synonyms": []}
    b = {**MUSHOKU_T1, "id": 2, "episodes": 24, "synonyms": []}
    m, _ = best_match("Mushoku Tensei: Isekai Ittara Honki Dasu", [a, b], episodes=24)
    assert m["id"] == 2


def test_sem_match_devolve_none():
    assert best_match("One Piece", CANDIDATOS) is None


def test_season_queries():
    q = season_queries("Konosuba", {"season_number": 2, "season_title": "Season 2"})
    assert q[0].startswith("Konosuba") and "Konosuba" in q[-1]

    # título próprio de temporada vira busca específica
    q = season_queries("Konosuba", {"season_number": 3, "season_title": "Legend of Crimson"})
    assert "Konosuba Legend of Crimson" in q

    # temporada 1 não gera busca redundante "Season 1"
    q = season_queries("Bleach", {"season_number": 1, "season_title": "Season 1"})
    assert q == ["Bleach"], q


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
