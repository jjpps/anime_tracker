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
