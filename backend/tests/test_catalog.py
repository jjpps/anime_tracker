"""Checagem do catálogo local: caminho, download e mapa de ids. Sem rede.

    python tests/test_catalog.py
"""

import json
import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker import catalog  # noqa: E402
from anime_tracker.config import RAIZ  # noqa: E402

OBRA = {
    "sources": ["https://anilist.co/anime/108465", "https://myanimelist.net/anime/39535"],
    "title": "Mushoku Tensei", "episodes": 11, "type": "TV", "status": "FINISHED",
    "synonyms": ["Jobless Reincarnation"],
}


def catalogo_falso(obras=(OBRA,)):
    """Grava um catálogo mínimo e devolve o caminho."""
    caminho = os.path.join(tempfile.mkdtemp(), "anime-db.json")
    with open(caminho, "w", encoding="utf-8") as fh:
        json.dump({"data": list(obras)}, fh)
    catalog._memo.pop(caminho, None)
    return caminho


def test_caminho_ancora_na_raiz():
    """`match --offline` precisa achar o arquivo de qualquer diretório."""
    anterior = os.environ.pop("ANIME_DB_JSON", None)
    try:
        assert catalog.caminho_db() == os.path.join(RAIZ, ".cache/anime-db.json")
        assert catalog.caminho_db("/tmp/x.json") == "/tmp/x.json"
    finally:
        if anterior is not None:
            os.environ["ANIME_DB_JSON"] = anterior


def test_arquivo_ausente_vira_excecao():
    """Exceção, não sys.exit: isso roda em thread do servidor."""
    try:
        catalog.carregar("/caminho/que/nao/existe.json")
        raise AssertionError("deveria avisar que falta o catálogo")
    except catalog.CatalogoAusente as e:
        assert "não encontrado" in str(e)


def test_garantir_baixa_quando_falta():
    """O app busca a própria dependência em vez de mandar rodar curl."""
    destino = os.path.join(tempfile.mkdtemp(), "anime-db.json")
    chamou = []

    def falso_baixar(caminho, progresso=None):
        chamou.append(caminho)
        with open(caminho, "w") as fh:
            fh.write('{"data": []}')
        return caminho

    original, catalog.baixar = catalog.baixar, falso_baixar
    try:
        assert catalog.garantir(destino) == destino
        assert chamou == [destino], "deveria baixar quando falta"
        assert catalog.garantir(destino) == destino
        assert len(chamou) == 1, "não pode baixar de novo com o arquivo presente"
    finally:
        catalog.baixar = original


def test_arquivo_lido_uma_vez_so():
    """São 62 MB e dois consumidores; parsear duas vezes custava segundos."""
    caminho = catalogo_falso()
    leituras = []
    original = catalog.json.load

    def contando(fh):
        leituras.append(1)
        return original(fh)

    catalog.json.load = contando
    try:
        catalog.carregar(caminho)
        catalog.mapa_anilist_para_mal(caminho)
        catalog.OfflineIndex(caminho)
        assert len(leituras) == 1, f"leu {len(leituras)} vezes"
    finally:
        catalog.json.load = original


def test_mapa_cruza_os_dois_ids():
    mapa = catalog.mapa_anilist_para_mal(catalogo_falso())
    assert mapa == {108465: (39535, "Mushoku Tensei", 11, "TV", "FINISHED")}


def test_obra_sem_um_dos_ids_fica_de_fora():
    """Sem o par, não há como levar o match do AniList até o MyAnimeList."""
    so_anilist = {**OBRA, "sources": ["https://anilist.co/anime/1"]}
    so_mal = {**OBRA, "sources": ["https://myanimelist.net/anime/2"]}
    assert catalog.mapa_anilist_para_mal(catalogo_falso([so_anilist, so_mal])) == {}


def test_indice_acha_por_titulo_e_sinonimo():
    idx = catalog.OfflineIndex(catalogo_falso())
    for termo in ("Mushoku Tensei", "Jobless Reincarnation"):
        achados = idx.search_many([termo])[termo]
        assert achados and achados[0]["id"] == 108465, termo


def test_indice_ignora_obra_sem_anilist_id():
    idx = catalog.OfflineIndex(catalogo_falso([{**OBRA, "sources": ["https://myanimelist.net/anime/2"]}]))
    assert idx.media == []


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
