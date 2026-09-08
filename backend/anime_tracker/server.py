"""Servidor HTTP: serve o frontend, a API de revisão e o callback do AniList.

Regra de camada: aqui não mora regra de negócio. Tudo vem de db.py, que é o
que o frontend consome.
"""

import contextlib
import os
import secrets
import threading

from flask import Flask, jsonify, redirect, request, send_from_directory

from . import db, oauth, sync
from .crunchyroll import Crunchyroll, CrunchyrollError
from .config import load_env

FRONTEND = os.path.join(os.path.dirname(__file__), "..", "..", "frontend")


def create_app(db_path=None):
    load_env()
    app = Flask(__name__, static_folder=None)

    def conn():
        # `with sqlite3.connect(...)` só controla transação e NÃO fecha a
        # conexão; sem o closing cada request vazaria uma
        return contextlib.closing(db.connect(db_path))

    def linhas(rows):
        return [dict(r) for r in rows]

    # estado do sync em andamento; só uma thread por vez
    estado_sync = {"rodando": False, "etapa": "", "feito": 0, "total": 0,
                   "resultado": None, "erro": None}
    trava = threading.Lock()

    # --- frontend ---

    @app.get("/")
    def index():
        return send_from_directory(FRONTEND, "index.html")

    @app.get("/<path:arquivo>")
    def estatico(arquivo):
        return send_from_directory(FRONTEND, arquivo)

    # --- API ---

    @app.get("/api/stats")
    def stats():
        with conn() as c:
            dados = db.stats(c)
            dados["anilist_conectado"] = bool(db.get_setting(c, oauth.TOKEN_KEY))
        return jsonify(dados)

    @app.get("/api/catalog")
    def catalog():
        """Menu 1: o que tem correspondência no AniList, revisado ou não."""
        with conn() as c:
            return jsonify(_filtrar(linhas(db.catalog(c)), request.args.get("q", "")))

    @app.get("/api/pending")
    def pending():
        """Menu 2: o que falta revisar."""
        with conn() as c:
            return jsonify(_filtrar(linhas(db.pending_review(c)), request.args.get("q", "")))

    @app.post("/api/review/<season_id>")
    def review(season_id):
        corpo = request.get_json(silent=True) or {}
        status = corpo.get("status")
        if status not in ("confirmed", "rejected", "pending"):
            return jsonify({"erro": "status deve ser confirmed, rejected ou pending"}), 400
        anilist_id = corpo.get("anilist_id")
        if anilist_id is not None:
            try:
                anilist_id = int(anilist_id)
            except (TypeError, ValueError):
                return jsonify({"erro": "anilist_id deve ser inteiro"}), 400
        with conn() as c:
            n = db.set_review(c, season_id, status, anilist_id)
        if not n:
            return jsonify({"erro": "season_id não encontrado"}), 404
        return jsonify({"season_id": season_id, "status": status})

    @app.get("/api/sync")
    def sync_status():
        with conn() as c:
            falta = sync.minutos_ate_liberar(c, _ttl())
            ultimo = db.get_setting(c, sync.ULTIMO_SYNC)
        return jsonify({**estado_sync, "minutos_ate_liberar": falta, "ultimo_sync": ultimo})

    @app.post("/api/sync")
    def sync_start():
        corpo = request.get_json(silent=True) or {}
        force = bool(corpo.get("force"))

        with trava:
            if estado_sync["rodando"]:
                return jsonify({"erro": "sync já em andamento"}), 409
            if not force:
                with conn() as c:
                    falta = sync.minutos_ate_liberar(c, _ttl())
                if falta:
                    return jsonify({"erro": f"sincronizado há pouco; tente em {falta} min",
                                    "minutos_ate_liberar": falta}), 429
            if not os.environ.get("CR_ETP_RT"):
                return jsonify({"erro": "defina CR_ETP_RT no .env"}), 500
            estado_sync.update(rodando=True, etapa="conectando", feito=0, total=0,
                               resultado=None, erro=None)

        threading.Thread(target=_rodar_sync, args=(force,), daemon=True).start()
        return jsonify({"iniciado": True}), 202

    def _rodar_sync(force):
        def progresso(texto, feito, total):
            estado_sync.update(etapa=texto, feito=feito, total=total)

        try:
            cr = Crunchyroll().login(os.environ["CR_ETP_RT"])
            with conn() as c:
                estado_sync["resultado"] = sync.run(cr, c, force=force,
                                                    ttl_horas=_ttl(), progresso=progresso)
        except (CrunchyrollError, sync.SyncBloqueado) as e:
            estado_sync["erro"] = str(e)
        except Exception as e:  # a thread não pode morrer calada
            estado_sync["erro"] = f"{type(e).__name__}: {e}"
        finally:
            estado_sync.update(rodando=False, etapa="")

    # --- OAuth do AniList ---

    @app.get("/auth/anilist")
    def auth_start():
        client_id, _, redirect_uri = oauth.credentials()
        if not client_id:
            return jsonify({"erro": "defina ANILIST_CLIENT_ID"}), 500
        state = oauth.new_state()
        with conn() as c:
            db.set_setting(c, oauth.STATE_KEY, state)
        return redirect(oauth.authorize_url(client_id, redirect_uri, state))

    @app.get("/auth/anilist/callback")
    def auth_callback():
        client_id, client_secret, redirect_uri = oauth.credentials()
        code = request.args.get("code")
        recebido = request.args.get("state", "")
        if not code:
            return jsonify({"erro": request.args.get("error", "callback sem code")}), 400

        with conn() as c:
            esperado = db.get_setting(c, oauth.STATE_KEY, "")
            # state confere a origem do callback; sem isso qualquer página
            # poderia disparar a troca do code
            if not esperado or not secrets.compare_digest(esperado, recebido):
                return jsonify({"erro": "state inválido"}), 400
            db.set_setting(c, oauth.STATE_KEY, "")
            try:
                token = oauth.exchange_code(code, client_id, client_secret, redirect_uri)
            except oauth.OAuthError as e:
                return jsonify({"erro": str(e)}), 502
            db.set_setting(c, oauth.TOKEN_KEY, token)
        return redirect("/?anilist=ok")

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
