"""Checagem do XML do MyAnimeList e do cálculo de progresso. Sem rede.

    python tests/test_export.py
"""

import os
import sys
import tempfile
import xml.etree.ElementTree as ET

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import db, export_mal, mal  # noqa: E402
from anime_tracker.progress import progresso_da_temporada  # noqa: E402

SERIE = {
    "series_id": "G1", "series_title": "Mushoku Tensei", "availability": "available",
    "total_episodes": 60, "total_seasons": 3, "added_at": None, "is_favorite": False,
}
MAPA = {108465: (39535, "Mushoku Tensei", 11, "TV", "FINISHED"),
        146065: (51179, "Mushoku Tensei II", 12, "TV", "FINISHED")}


def banco():
    conn = db.connect(":memory:")
    db.save_series(conn, [SERIE])
    db.save_seasons(conn, "G1", [
        {"season_id": "S1", "season_number": 1, "season_title": "Season 1",
         "total_episodes": 11, "years": (2021, 2022)},
        {"season_id": "S2", "season_number": 2, "season_title": "Season 2",
         "total_episodes": 12, "years": (2023, 2024)},
    ])
    db.save_matches(conn, [
        {"season_id": "S1", "season_number": 1, "anilist_id": 108465,
         "anilist_title": "Mushoku Tensei", "anilist_episodes": 11,
         "anilist_url": "", "confidence": 1.0},
        {"season_id": "S2", "season_number": 2, "anilist_id": 146065,
         "anilist_title": "Mushoku Tensei II", "anilist_episodes": 12,
         "anilist_url": "", "confidence": 1.0},
    ])
    return conn


def test_progresso_usa_o_maior_episodio():
    # One Piece numera de forma absoluta: contar episódios do arco daria 3
    assert progresso_da_temporada({1171.0, 1172.0, 1173.0}) == 1173


def test_progresso_limita_ao_total_da_obra():
    # CR junta o que o MAL separa: 24 assistidos contra uma obra de 11
    assert progresso_da_temporada(set(range(1, 25)), total_da_obra=11) == 11
    assert progresso_da_temporada(set(), total_da_obra=11) == 0


def test_xml_tem_id_do_mal_preenchido():
    """O exemplo de referência deixa o campo vazio e depende de casar título."""
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.save_history(conn, [
        {"episode_id": f"e{n}", "series_id": "G1", "series_title": "Mushoku Tensei",
         "season_number": 1, "episode_number": float(n), "episode_title": "",
         "watched_at": "2026-01-01T00:00:00Z", "fully_watched": True}
        for n in range(1, 25)
    ])
    caminho = tempfile.mktemp(suffix=".xml")
    r = export_mal.exportar(conn, caminho)

    raiz = ET.parse(caminho).getroot()
    animes = raiz.findall("anime")
    assert r["obras"] == 2 and len(animes) == 2
    ids = [a.findtext("series_animedb_id") for a in animes]
    assert all(i and i.isdigit() for i in ids), ids

    por_id = {a.findtext("series_animedb_id"): a for a in animes}
    t1 = por_id["39535"]
    # 24 assistidos na CR, obra de 11 no MAL: exporta 11, não 24
    assert t1.findtext("my_watched_episodes") == "11"
    assert t1.findtext("my_status") == "Completed"
    assert t1.findtext("update_on_import") == "1"
    assert por_id["51179"].findtext("my_status") == "Plan to Watch"


def test_xml_agrupa_temporadas_na_mesma_obra():
    """One Piece: 24 temporadas na CR, uma obra no MAL — um nó só."""
    conn = banco()
    conn.execute("UPDATE matches SET mal_id = 21, mal_episodes = 1168, "
                 "mal_title = 'One Piece'")
    conn.commit()
    db.save_history(conn, [
        {"episode_id": "a", "series_id": "G1", "series_title": "One Piece",
         "season_number": 1, "episode_number": 60.0, "episode_title": "",
         "watched_at": "2026-01-01T00:00:00Z", "fully_watched": True},
        {"episode_id": "b", "series_id": "G1", "series_title": "One Piece",
         "season_number": 2, "episode_number": 1173.0, "episode_title": "",
         "watched_at": "2026-01-02T00:00:00Z", "fully_watched": True},
    ])
    caminho = tempfile.mktemp(suffix=".xml")
    r = export_mal.exportar(conn, caminho)

    animes = ET.parse(caminho).getroot().findall("anime")
    assert len(animes) == 1, "duas entradas com o mesmo id brigariam no import"
    assert r["obras"] == 1 and r["temporadas"] == 2
    # vence o maior progresso (1173 do arco recente, não 60), limitado ao
    # total que o MAL declara para a obra
    assert animes[0].findtext("my_watched_episodes") == "1168"


def test_xml_ignora_rejeitados():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.set_review(conn, "S1", "rejected")
    caminho = tempfile.mktemp(suffix=".xml")
    assert export_mal.exportar(conn, caminho)["obras"] == 1


def test_xml_so_confirmados():
    conn = banco()
    mal.resolver_ids(conn, MAPA)
    db.set_review(conn, "S1", "confirmed")
    caminho = tempfile.mktemp(suffix=".xml")
    assert export_mal.exportar(conn, caminho, apenas_confirmados=True)["obras"] == 1


def test_xml_sem_mal_id_fica_de_fora():
    """Sem id, o import cairia no casamento por título — melhor não exportar."""
    conn = banco()
    caminho = tempfile.mktemp(suffix=".xml")
    assert export_mal.exportar(conn, caminho)["obras"] == 0


def test_status_de():
    assert export_mal.status_de(0, 12) == "Plan to Watch"
    assert export_mal.status_de(5, 12) == "Watching"
    assert export_mal.status_de(12, 12) == "Completed"
    assert export_mal.status_de(5, 0) == "Watching"  # sem total, não afirma completo


def test_obra_no_ar_nao_vira_completo():
    """One Piece: assistiu tudo que existe, mas a série continua. Está em dia."""
    assert export_mal.status_de(1168, 1168, em_exibicao=True) == "Watching"
    assert export_mal.status_de(1168, 1168, em_exibicao=False) == "Completed"


def test_cr_juntando_cours_ainda_conta_como_completo():
    """27 das 28 temporadas que passam do total são obras encerradas."""
    assert export_mal.status_de(11, 11, em_exibicao=False) == "Completed"


def test_xml_marca_serie_no_ar_como_watching():
    conn = banco()
    conn.execute("UPDATE matches SET mal_id = 21, mal_episodes = 1168, "
                 "mal_title = 'One Piece', mal_status = 'ONGOING'")
    conn.commit()
    db.save_history(conn, [
        {"episode_id": "a", "series_id": "G1", "series_title": "One Piece",
         "season_number": 1, "episode_number": 1173.0, "episode_title": "",
         "watched_at": "2026-01-01T00:00:00Z", "fully_watched": True}])
    caminho = tempfile.mktemp(suffix=".xml")
    export_mal.exportar(conn, caminho)
    no = ET.parse(caminho).getroot().find("anime")
    assert no.findtext("my_watched_episodes") == "1168"
    assert no.findtext("my_status") == "Watching", "marcaria uma série no ar como concluída"

if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
