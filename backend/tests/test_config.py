"""Checagem do loader de .env.

    python tests/test_config.py
"""

import os
import sys
import tempfile

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from anime_tracker.config import load_env, parse_env  # noqa: E402


def test_parse_basico():
    v = parse_env("CR_ETP_RT=abc123\nANILIST_CLIENT_ID=12345\n")
    assert v == {"CR_ETP_RT": "abc123", "ANILIST_CLIENT_ID": "12345"}


def test_ignora_comentario_e_vazio():
    v = parse_env("# comentário\n\n  \nCHAVE=valor\n# outro\n")
    assert v == {"CHAVE": "valor"}


def test_aspas_sao_delimitador():
    v = parse_env('A="com espaço"\nB=\'simples\'\nC=sem\n')
    assert v == {"A": "com espaço", "B": "simples", "C": "sem"}


def test_prefixo_export():
    assert parse_env("export CHAVE=valor\n") == {"CHAVE": "valor"}


def test_valor_com_igual():
    """Secret e URL costumam ter '=' e ':' no meio; só o primeiro = separa."""
    v = parse_env("SECRET=abc=def==\nURL=http://localhost:8000/auth/cb\n")
    assert v["SECRET"] == "abc=def=="
    assert v["URL"] == "http://localhost:8000/auth/cb"


def test_valor_vazio():
    assert parse_env("VAZIA=\n") == {"VAZIA": ""}


def test_shell_vence_o_arquivo():
    """Sobrepor pelo shell sem editar o .env é o comportamento esperado."""
    arquivo = tempfile.mktemp(suffix=".env")
    with open(arquivo, "w") as fh:
        fh.write("JA_DEFINIDA=do-arquivo\nSO_NO_ARQUIVO=do-arquivo\n")

    os.environ["JA_DEFINIDA"] = "do-shell"
    os.environ.pop("SO_NO_ARQUIVO", None)
    try:
        assert load_env(arquivo) == arquivo
        assert os.environ["JA_DEFINIDA"] == "do-shell"
        assert os.environ["SO_NO_ARQUIVO"] == "do-arquivo"
    finally:
        os.environ.pop("JA_DEFINIDA", None)
        os.environ.pop("SO_NO_ARQUIVO", None)


def test_sem_arquivo_nao_estoura():
    assert load_env("/caminho/que/nao/existe/.env") is None


def test_catalogo_ancora_na_raiz():
    """`match --offline` precisa achar o arquivo de qualquer diretório."""
    from anime_tracker.catalog import CatalogoAusente, OfflineIndex, caminho_db
    from anime_tracker.config import RAIZ

    anterior = os.environ.pop("ANIME_DB_JSON", None)
    try:
        assert caminho_db() == os.path.join(RAIZ, ".cache/anime-db.json")
        assert caminho_db("/tmp/x.json") == "/tmp/x.json"

        os.environ["ANIME_DB_JSON"] = "nao-existe.json"
        try:
            OfflineIndex()
            raise AssertionError("deveria avisar que falta o catálogo")
        except CatalogoAusente as e:
            # a mensagem tem que ensinar a resolver, inclusive sem make
            assert "curl" in str(e) and "make db" in str(e)
    finally:
        os.environ.pop("ANIME_DB_JSON", None)
        if anterior is not None:
            os.environ["ANIME_DB_JSON"] = anterior


def test_garantir_baixa_quando_falta(tmp=None):
    """O app busca a própria dependência em vez de mandar rodar curl."""
    import tempfile
    from anime_tracker import catalog

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


def test_exemplo_do_repo_e_valido():
    """O .env.example precisa ter todas as chaves que o código lê."""
    raiz = os.path.join(os.path.dirname(__file__), "..", "..")
    with open(os.path.join(raiz, ".env.example"), encoding="utf-8") as fh:
        chaves = parse_env(fh.read())
    for esperada in ("CR_ETP_RT", "ANILIST_CLIENT_ID", "ANILIST_CLIENT_SECRET",
                     "ANILIST_REDIRECT_URI", "ANIME_TRACKER_DB", "MAL_CLIENT_ID"):
        assert esperada in chaves, f"{esperada} faltando no .env.example"


if __name__ == "__main__":
    for nome, fn in sorted(globals().items()):
        if nome.startswith("test_"):
            fn()
            print("ok", nome)
