"""OAuth do AniList (Authorization Code Grant com callback em localhost).

Particularidades da implementação deles, que mudam o desenho:
  - o token vale 1 ano e NÃO existe refresh token: não há fluxo de renovação
    para escrever, quando expira o usuário reautentica;
  - scopes não são suportados — o token dá acesso quase total à conta, então
    guardá-lo é guardar uma credencial forte;
  - o redirect_uri da requisição tem que bater exatamente com o cadastrado.
"""

import os
import secrets
import urllib.parse

import requests

AUTHORIZE = "https://anilist.co/api/v2/oauth/authorize"
TOKEN = "https://anilist.co/api/v2/oauth/token"
STATE_KEY = "anilist_oauth_state"
TOKEN_KEY = "anilist_access_token"


class OAuthError(Exception):
    pass


def credentials():
    """(client_id, client_secret, redirect_uri) do ambiente."""
    return (
        os.environ.get("ANILIST_CLIENT_ID", ""),
        os.environ.get("ANILIST_CLIENT_SECRET", ""),
        os.environ.get("ANILIST_REDIRECT_URI", "http://localhost:8000/auth/anilist/callback"),
    )


def authorize_url(client_id, redirect_uri, state):
    return AUTHORIZE + "?" + urllib.parse.urlencode({
        "client_id": client_id,
        "redirect_uri": redirect_uri,
        "response_type": "code",
        "state": state,
    })


def new_state():
    return secrets.token_urlsafe(24)


def exchange_code(code, client_id, client_secret, redirect_uri):
    """Troca o authorization code pelo access token."""
    resp = requests.post(
        TOKEN,
        json={
            "grant_type": "authorization_code",
            "client_id": client_id,
            "client_secret": client_secret,
            "redirect_uri": redirect_uri,
            "code": code,
        },
        headers={"Content-Type": "application/json", "Accept": "application/json"},
        timeout=30,
    )
    if not resp.ok:
        raise OAuthError(f"troca do code falhou ({resp.status_code}): {resp.text[:200]}")
    token = resp.json().get("access_token")
    if not token:
        raise OAuthError("resposta sem access_token")
    return token
