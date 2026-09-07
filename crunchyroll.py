"""Cliente mínimo da API do Crunchyroll (auth via cookie etp_rt + watch history).

Extraído de github.com/ruflas/crunchyexporter-cli — só o que é essencial.

Como obter o etp_rt:
  1. Logar em crunchyroll.com no navegador
  2. DevTools -> Application -> Cookies -> https://www.crunchyroll.com
  3. Copiar o valor do cookie 'etp_rt'
"""

import base64
import uuid

import requests

API = "https://beta-api.crunchyroll.com"
# Client ID público embutido no web app da CR (mesmo usado pelo crunchy-cli).
CLIENT_ID = "noaihdevm_6iyg0a8l0q"
CLIENT_SECRET = ""


class CrunchyrollError(Exception):
    pass


class Crunchyroll:
    def __init__(self, client_id=CLIENT_ID, client_secret=CLIENT_SECRET):
        self.auth_header = "Basic " + base64.b64encode(
            f"{client_id.rstrip(':')}:{client_secret}".encode()
        ).decode()
        self.session = requests.Session()
        self.session.headers["User-Agent"] = "Mozilla/5.0"
        self.access_token = self.refresh_token = self.account_id = None

    # --- auth ---

    def login(self, etp_rt: str):
        """Grant etp_rt_cookie. A CR removeu o grant de password."""
        return self._token(
            {
                "grant_type": "etp_rt_cookie",
                "scope": "offline_access",
                "device_id": str(uuid.uuid4()),
                "device_name": "Chrome on Windows",
                "device_type": "com.crunchyroll.desktop.windows",
            },
            cookies={"etp_rt": etp_rt},
        )

    def refresh(self, refresh_token=None):
        return self._token(
            {
                "grant_type": "refresh_token",
                "refresh_token": refresh_token or self.refresh_token,
                "scope": "offline_access",
            }
        )

    def _token(self, data, cookies=None):
        resp = self.session.post(
            f"{API}/auth/v1/token",
            headers={"Authorization": self.auth_header},
            data=data,
            cookies=cookies,
            timeout=15,
        )
        if not resp.ok:
            raise CrunchyrollError(f"auth falhou ({resp.status_code}): {resp.text}")

        payload = resp.json()
        self.access_token = payload["access_token"]
        self.refresh_token = payload.get("refresh_token", self.refresh_token)
        self.session.headers["Authorization"] = f"Bearer {self.access_token}"
        self.account_id = self._get("/accounts/v1/me")["account_id"]
        return self

    # --- conteúdo ---

    def watch_history(self, locale="en-US", page_size=100):
        """Itera o histórico de episódios assistidos."""
        return self._paginate("watch-history", parse_history_item, locale, page_size)

    def watchlist(self, locale="en-US", page_size=100):
        """Itera a lista de animes salvos (watchlist)."""
        return self._paginate("watchlist", parse_watchlist_item, locale, page_size)

    def _paginate(self, endpoint, parse, locale, page_size):
        page = 1
        while True:
            items = self._get(
                f"/content/v2/{self.account_id}/{endpoint}",
                params={"page": page, "page_size": page_size, "locale": locale},
            ).get("data", [])
            yield from (parse(i) for i in items if i.get("panel"))
            if len(items) < page_size:
                return
            page += 1

    def _get(self, path, params=None):
        resp = self.session.get(f"{API}{path}", params=params, timeout=20)
        if not resp.ok:
            raise CrunchyrollError(f"GET {path} falhou ({resp.status_code}): {resp.text}")
        return resp.json()


def parse_history_item(item: dict) -> dict:
    """Achata um item do watch-history nos campos que interessam."""
    panel = item["panel"]
    meta = panel.get("episode_metadata", {})
    return {
        "series_id": meta.get("series_id") or panel.get("id", ""),
        "series_title": meta.get("series_title") or panel.get("title", "unknown"),
        "season_number": _num(meta.get("season_number"), int, 1),
        "episode_number": _num(meta.get("episode_number"), float, 0.0),
        "episode_id": panel.get("id", ""),
        "episode_title": panel.get("title", ""),
        "watched_at": item.get("date_played"),
        "fully_watched": item.get("fully_watched", False),
    }


def parse_watchlist_item(item: dict) -> dict:
    """Achata um item da watchlist. O panel aqui é a série, não o episódio."""
    panel = item["panel"]
    meta = panel.get("series_metadata", {})
    return {
        "series_id": panel.get("id", ""),
        "series_title": panel.get("title", "unknown"),
        "total_episodes": _num(meta.get("episode_count"), int, 0),
        "total_seasons": _num(meta.get("season_count"), int, 0),
        "added_at": item.get("date_added"),
        "is_favorite": item.get("is_favorite", False),
        "never_watched": item.get("never_watched", False),
        "fully_watched": item.get("fully_watched", False),
    }


def _num(value, cast, default):
    try:
        return cast(value) if value is not None else default
    except (TypeError, ValueError):
        return default


if __name__ == "__main__":
    # sanity check do parser (o resto precisa de rede/credencial)
    ep = parse_history_item(
        {
            "panel": {
                "id": "GX9UQ",
                "title": "Ep 1",
                "episode_metadata": {
                    "series_id": "S1",
                    "series_title": "Frieren",
                    "season_number": "1",
                    "episode_number": 1,
                },
            },
            "date_played": "2026-01-01T00:00:00Z",
            "fully_watched": True,
        }
    )
    assert ep["series_title"] == "Frieren" and ep["episode_number"] == 1.0
    assert ep["fully_watched"] is True

    orphan = parse_history_item({"panel": {"id": "X", "title": "Filme"}})
    assert orphan["series_title"] == "Filme"
    assert orphan["season_number"] == 1 and orphan["episode_number"] == 0.0

    junk = parse_history_item({"panel": {"episode_metadata": {"season_number": "n/a"}}})
    assert junk["season_number"] == 1

    wl = parse_watchlist_item(
        {
            "panel": {
                "id": "GY5P48XEY",
                "title": "Frieren",
                "series_metadata": {"episode_count": 28, "season_count": 1},
            },
            "date_added": "2026-01-01T00:00:00Z",
            "is_favorite": True,
        }
    )
    assert wl["series_id"] == "GY5P48XEY" and wl["total_episodes"] == 28
    assert wl["is_favorite"] is True and wl["never_watched"] is False

    bare = parse_watchlist_item({"panel": {"id": "X"}})
    assert bare["series_title"] == "unknown" and bare["total_episodes"] == 0
    print("ok")
