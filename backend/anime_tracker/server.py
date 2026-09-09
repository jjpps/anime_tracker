"""Servidor HTTP: serve o frontend, a API de revisão e o callback do AniList.

Regra de camada: aqui não mora regra de negócio. Tudo vem de db.py, que é o
que o frontend consome.
"""

import contextlib
import logging
import os
import threading

from flask import Flask, jsonify, redirect, request, send_from_directory

from . import db, sync
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
    # os logs do AniList e do sync saem no terminal junto com os do Flask
    logging.basicConfig(level=logging.INFO, format="%(name)s: %(message)s")
    load_env()
    app = Flask(__name__, static_folder=None)

    def conn():
        # `with sqlite3.connect(...)` só controla transação e NÃO fecha a
        # conexão; sem o closing cada request vazaria uma
        return contextlib.closing(db.connect(db_path))

    def linhas(rows):
        return [dict(r) for r in rows]

    # uma tarefa de fundo por vez: sync e match mexem nas mesmas tabelas
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
        from .catalog import caminho_db

        with conn() as c:
            dados = db.stats(c)
        # sem AniList e sem catálogo local não há como casar; a UI precisa saber
        dados["catalogo_local"] = os.path.exists(caminho_db())
        return jsonify(dados)

    @app.get("/api/library")
    def library():
        """3. biblioteca: os matches já resolvidos."""
        with conn() as c:
            return jsonify(_filtrar(linhas(db.biblioteca(c)), request.args.get("q", "")))

    @app.get("/api/pending")
    def pending():
        """4. pendentes de match: o que não fechou em 1.00."""
        with conn() as c:
            return jsonify(_filtrar(linhas(db.pendentes(c)), request.args.get("q", "")))

    @app.post("/api/link/<season_id>")
    def link(season_id):
        """5. vincula o id do provedor ao anime, na mão."""
        corpo = request.get_json(silent=True) or {}
        provider = corpo.get("provider")
        if provider not in db.PROVIDERS:
            return jsonify({"erro": f"provider deve ser um de {db.PROVIDERS}"}), 400
        try:
            provider_id = int(corpo.get("provider_id"))
        except (TypeError, ValueError):
            return jsonify({"erro": "provider_id deve ser inteiro"}), 400

        with conn() as c:
            n = db.vincular(c, season_id, provider, provider_id, corpo.get("title"))
        if not n:
            return jsonify({"erro": "season_id não encontrado"}), 404
        return jsonify({"season_id": season_id, "provider": provider,
                        "provider_id": provider_id})

    @app.post("/api/dismiss/<season_id>")
    def dismiss(season_id):
        """Tira da fila o que não tem par no provedor (filme, especial...)."""
        with conn() as c:
            n = db.set_review(c, season_id, "rejected")
        if not n:
            return jsonify({"erro": "season_id não encontrado"}), 404
        return jsonify({"season_id": season_id, "status": "rejected"})

    @app.get("/api/task")
    def task_status():
        with conn() as c:
            falta = sync.minutos_ate_liberar(c, _ttl())
            ultimo = db.get_setting(c, sync.ULTIMO_SYNC)
        return jsonify({**tarefa, "minutos_ate_liberar": falta, "ultimo_sync": ultimo})

    @app.post("/api/crunchyroll")
    def crunchyroll_start():
        """Baixa a Crunchyroll, sem casar: o match é dos botões de provedor."""
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
            cr = Crunchyroll().login(os.environ["CR_ETP_RT"])
            with conn() as c:
                return sync.run(cr, c, force=True, progresso=progresso, matcher=None)

        return iniciar("crunchyroll", executar)

    @app.post("/api/provider/<provider>")
    def provider_start(provider):
        """Procura as séries da nossa base Crunchyroll no provedor escolhido."""
        if provider not in db.PROVIDERS:
            return jsonify({"erro": f"provider deve ser um de {db.PROVIDERS}"}), 400
        todas = bool((request.get_json(silent=True) or {}).get("todas"))

        def executar(progresso):
            with conn() as c:
                r = sync.rodar_match(c, todas=todas, provider=provider,
                                     progresso=progresso)
                r["pendentes"] = len(db.pendentes(c))
            return r

        return iniciar(provider, executar)


    return app


def _ttl():
    try:
        return int(os.environ.get("SYNC_TTL_HORAS", sync.TTL_HORAS))
    except ValueError:
        return sync.TTL_HORAS


def _filtrar(rows, q):
    if not q:
        return rows
    q = q.lower()
    return [r for r in rows if q in (r.get("series_title") or "").lower()]
