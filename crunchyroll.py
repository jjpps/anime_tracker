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
        """Itera a watchlist. O endpoint só devolve ids, então resolvemos
        os metadados em lote via cms/objects."""
        entries = {e["id"]: e for e in self._paginate("watchlist", dict, locale, page_size)}
        ids = list(entries)
        for chunk in (ids[i : i + 50] for i in range(0, len(ids), 50)):
            objects = self._get(
                "/content/v2/cms/objects/" + ",".join(chunk),
                params={"locale": locale, "ratings": "false"},
            ).get("data", [])
            for obj in objects:
                yield parse_watchlist_item(obj, entries.pop(obj["id"], {}))
        # ids que o cms não resolveu (conteúdo removido/fora da região) viram stub
        # em vez de sumir calados
        for series_id, entry in entries.items():
            yield parse_watchlist_item({"id": series_id}, entry)

    def _paginate(self, endpoint, parse, locale, page_size):
        page = 1
        while True:
            items = self._get(
                f"/content/v2/{self.account_id}/{endpoint}",
                params={"page": page, "page_size": page_size, "locale": locale},
            ).get("data", [])
            yield from (parse(i) for i in items)
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
    panel = item.get("panel") or {}
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


def parse_watchlist_item(obj: dict, entry: dict) -> dict:
    """Junta o objeto da série (cms/objects) com a entrada da watchlist."""
    meta = obj.get("series_metadata", {})
    return {
        "series_id": obj.get("id", ""),
        "series_title": obj.get("title", "unknown"),
        "total_episodes": _num(meta.get("episode_count"), int, 0),
        "total_seasons": _num(meta.get("season_count"), int, 0),
        # séries fora da região voltam com contagem zerada — vale saber por quê
        "availability": meta.get("availability_status", "unknown"),
        "added_at": entry.get("date_added"),
        "is_favorite": entry.get("is_favorite", False),
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
            "id": "GY5P48XEY",
            "title": "Frieren",
            "series_metadata": {"episode_count": 28, "season_count": 1},
        },
        {"date_added": "2026-01-01T00:00:00Z", "is_favorite": True},
    )
    assert wl["series_id"] == "GY5P48XEY" and wl["total_episodes"] == 28
    assert wl["is_favorite"] is True and wl["added_at"].startswith("2026")

    bare = parse_watchlist_item({"id": "X"}, {})
    assert bare["series_title"] == "unknown" and bare["total_episodes"] == 0
    assert bare["added_at"] is None and bare["is_favorite"] is False
    assert bare["availability"] == "unknown"
    print("ok")
