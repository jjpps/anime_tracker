"""Carrega o .env para o ambiente.

Loader próprio em vez de python-dotenv: o formato usado aqui é KEY=valor e
cabe em poucas linhas. Variável já definida no shell vence o arquivo, que é a
convenção — dá para sobrepor um valor sem editar o .env.
"""

import os

RAIZ = os.path.abspath(os.path.join(os.path.dirname(__file__), "..", ".."))


def parse_env(texto):
    """Texto do .env -> dict. Ignora comentários, linhas vazias e aspas."""
    valores = {}
    for linha in texto.splitlines():
        linha = linha.strip()
        if not linha or linha.startswith("#") or "=" not in linha:
            continue
        chave, _, valor = linha.partition("=")
        chave = chave.removeprefix("export ").strip()
        valor = valor.strip()
        # aspas são delimitador, não conteúdo
        if len(valor) >= 2 and valor[0] == valor[-1] and valor[0] in "\"'":
            valor = valor[1:-1]
        if chave:
            valores[chave] = valor
    return valores


def load_env(caminho=None):
    """Lê o .env da raiz do projeto (ou do cwd) e completa o os.environ."""
    candidatos = [caminho] if caminho else [os.path.join(RAIZ, ".env"), ".env"]
    for candidato in candidatos:
        if candidato and os.path.exists(candidato):
            with open(candidato, encoding="utf-8") as fh:
                for chave, valor in parse_env(fh.read()).items():
                    os.environ.setdefault(chave, valor)  # shell vence o arquivo
            return candidato
    return None
