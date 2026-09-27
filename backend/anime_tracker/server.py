"""Servidor HTTP: serve o frontend e a API.

Regra de camada: aqui não mora regra de negócio. Tudo vem de db.py, que é o
que o frontend consome.
"""

import contextlib
import logging
import os
import threading

from flask import Flask, jsonify, request, send_from_directory

from . import db, novidades, sync
from .crunchyroll import Crunchyroll, CrunchyrollError
from .config import load_env

# build do Angular; `npm run build` em frontend/web escreve aqui
FRONTEND = os.path.abspath(
    os.path.join(os.path.dirname(__file__), "..", "..", "frontend", "web", "dist", "web", "browser")
)
SEM_BUILD = """<!doctype html><meta charset="utf-8">
<title>anime tracker</title>
<body style="font:15px system-ui;background:#14161a;color:#e6e8ec;padding:40px">
<h1>Frontend não compilado</h1>
<p>O Angular precisa ser buildado uma vez:</p>
<pre style="background:#1c1f26;padding:12px;border-radius:6px">cd frontend/web
npm install
npm run build</pre>
<p>Esperado em <code>{}</code>.</p>"""


def create_app(db_path=None):
    # os logs do sync saem no terminal junto com os do Flask
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    load_env()
    app = Flask(__name__, static_folder=None)

    def conn():
        # `with sqlite3.connect(...)` só controla transação e NÃO fecha a
        # conexão; sem o closing cada request vazaria uma
        return contextlib.closing(db.connect(db_path))

    def linhas(rows):
        return [dict(r) for r in rows]

    # uma tarefa de fundo por vez: dois syncs mexeriam nas mesmas tabelas
    tarefa = {"rodando": False, "tipo": None, "etapa": "", "feito": 0, "total": 0,
              "resultado": None, "erro": None}
    trava = threading.Lock()

    def iniciar(tipo, executar):
        """Dispara `executar(progresso)` em thread, se nada estiver rodando."""
        with trava:
            if tarefa["rodando"]:
                return jsonify({"erro": f"{tarefa['tipo']} já em andamento"}), 409
            tarefa.update(rodando=True, tipo=tipo, etapa="iniciando", feito=0,
                          total=0, resultado=None, erro=None)

        def alvo():
            def progresso(texto, feito, total):
                tarefa.update(etapa=texto, feito=feito, total=total)

            try:
                tarefa["resultado"] = executar(progresso)
            except (CrunchyrollError, sync.SyncBloqueado) as e:
                tarefa["erro"] = str(e)
            except Exception as e:  # a thread não pode morrer calada
                tarefa["erro"] = f"{type(e).__name__}: {e}"
            finally:
                tarefa.update(rodando=False, etapa="")

        threading.Thread(target=alvo, daemon=True).start()
        return jsonify({"iniciado": True}), 202

    # --- frontend ---

    @app.get("/")
    def index():
        # instrução em vez de 404: quem clona não adivinha que falta um build
        if not os.path.exists(os.path.join(FRONTEND, "index.html")):
            return SEM_BUILD.format(FRONTEND), 503
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/<path:arquivo>")
    def estatico(arquivo):
        caminho = os.path.join(FRONTEND, arquivo)
        if os.path.isfile(caminho):
            return send_from_directory(FRONTEND, arquivo)
        return index()  # rota do Angular: quem resolve o caminho é o roteador dele

    # --- API ---

    @app.get("/api/stats")
    def stats():
        with conn() as c:
            return jsonify(db.stats(c))

    @app.get("/api/novidades")
    def lista_novidades():
        with conn() as c:
            return jsonify(novidades.lista(c))

    @app.get("/api/task")
    def task_status():
        with conn() as c:
            falta = sync.minutos_ate_liberar(c, _ttl())
            ultimo = db.get_setting(c, sync.ULTIMO_SYNC)
            erro_sync = db.get_setting(c, sync.ULTIMO_ERRO)
        return jsonify({**tarefa, "minutos_ate_liberar": falta, "ultimo_sync": ultimo,
                        "erro_sync": erro_sync})

    @app.post("/api/crunchyroll")
    def crunchyroll_start():
        """Baixa histórico, temporadas e episódios da Crunchyroll."""
        force = bool((request.get_json(silent=True) or {}).get("force"))
        if not force:
            with conn() as c:
                falta = sync.minutos_ate_liberar(c, _ttl())
            if falta:
                return jsonify({"erro": f"sincronizado há pouco; tente em {falta} min",
                                "minutos_ate_liberar": falta}), 429
        if not os.environ.get("CR_ETP_RT"):
            return jsonify({"erro": "defina CR_ETP_RT no .env"}), 500

        def executar(progresso):
            with conn() as c, sync.registrando_erro(c):
                cr = Crunchyroll().login(os.environ["CR_ETP_RT"])
                return sync.run(cr, c, force=True, progresso=progresso)

        return iniciar("crunchyroll", executar)

    return app


def _ttl():
    try:
        return int(os.environ.get("SYNC_TTL_HORAS", sync.TTL_HORAS))
    except ValueError:
        return sync.TTL_HORAS
