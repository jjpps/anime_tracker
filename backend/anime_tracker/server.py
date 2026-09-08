"""Servidor HTTP: serve o frontend, a API de revisão e o callback do AniList.

Regra de camada: aqui não mora regra de negócio. Tudo vem de db.py, que é o
que o frontend consome.
"""

import contextlib
import os
import secrets

from flask import Flask, jsonify, redirect, request, send_from_directory

from . import db, oauth
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
        """Menu 1: o que já foi revisado."""
        with conn() as c:
            return jsonify(_filtrar(linhas(db.reviewed(c)), request.args.get("q", "")))

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


def _filtrar(rows, q):
    if not q:
        return rows
    q = q.lower()
    return [r for r in rows if q in (r.get("series_title") or "").lower()]
