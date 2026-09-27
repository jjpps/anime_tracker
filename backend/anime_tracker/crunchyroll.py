"""Cliente mínimo da API do Crunchyroll (auth via cookie etp_rt, histórico, temporadas).

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

    def watch_history(self, locale="en-US", page_size=100, since=None):
        """Itera o histórico de episódios assistidos.

        `since` (ISO-8601) para o percurso ao alcançar o que já se conhece: a CR
        devolve o histórico ordenado por date_played desc, então o que está
        abaixo da marca já foi visto. Reassistir sobe o item para o topo, então
        esse caso é coberto sem tratamento especial.

        Parte dos itens vem sem `panel` (conteúdo tirado do catálogo). Eles ainda
        trazem os ids no nível do item, então dá para recuperar pelo menos a
        série — ignorá-los perderia ~14% do histórico."""
        orfaos = []
        for item in self._paginate("watch-history", dict, locale, page_size):
            if since and (item.get("date_played") or "") < since:
                break
            if item.get("panel"):
                yield parse_history_item(item)
            else:
                orfaos.append(item)

        series = self.resolve_objects(
            [i["parent_id"] for i in orfaos if i.get("parent_type") == "series"], locale
        )
        for item in orfaos:
            obj = series.get(item.get("parent_id"), {})
            yield parse_history_item(item, series_title=obj.get("title"))

    def resolve_objects(self, ids, locale="en-US", chunk_size=50):
        """id -> objeto do catálogo, em lote. Ids removidos simplesmente faltam."""
        ids = [i for i in dict.fromkeys(ids) if i]
        out = {}
        for i in range(0, len(ids), chunk_size):
            chunk = ids[i : i + chunk_size]
            try:
                data = self._get(
                    "/content/v2/cms/objects/" + ",".join(chunk),
                    params={"locale": locale, "ratings": "false"},
                ).get("data", [])
            except CrunchyrollError:
                continue  # lote inteiro fora do catálogo
            out.update({obj["id"]: obj for obj in data})
        return out

    def seasons(self, series_id, locale="en-US", with_episodes=True):
        """Temporadas de uma série, com os episódios de cada uma.

        Os episódios custam uma chamada por temporada, mas são o que mostra a
        continuação: a CR anexa a parte seguinte à mesma temporada, então só a
        data de cada episódio diz o que saiu depois."""
        data = self._get(f"/content/v2/cms/series/{series_id}/seasons",
                         params={"locale": locale}).get("data", [])
        out = []
        for s in data:
            season = {
                "season_id": s.get("id", ""),
                "season_number": _num(s.get("season_number"), int, 0),
                "season_title": s.get("title", ""),
                "total_episodes": _num(s.get("number_of_episodes"), int, 0),
                "episodes": [],
            }
            if with_episodes:
                season["episodes"] = self.episodes(season["season_id"], locale)
            out.append(season)
        return out

    def episodes(self, season_id, locale="en-US"):
        """[{episode_number, released_at}] de uma temporada."""
        data = self._get(f"/content/v2/cms/seasons/{season_id}/episodes",
                         params={"locale": locale}).get("data", [])
        return [ep for ep in map(parse_episode, data) if ep["episode_number"] is not None]

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


def parse_history_item(item: dict, series_title=None) -> dict:
    """Achata um item do watch-history nos campos que interessam.

    Sem panel não há como saber temporada e episódio: ficam None em vez de
    virarem T1E0, que contaria como episódio assistido que nunca existiu."""
    panel = item.get("panel") or {}
    meta = panel.get("episode_metadata", {})
    pai = item.get("parent_id", "") if item.get("parent_type") == "series" else ""
    return {
        "series_id": meta.get("series_id") or pai or panel.get("id", ""),
        "series_title": meta.get("series_title") or panel.get("title") or series_title or "unknown",
        "season_number": _num(meta.get("season_number"), int, 1) if panel else None,
        "episode_number": _num(meta.get("episode_number"), float, 0.0) if panel else None,
        "episode_id": panel.get("id") or item.get("id", ""),
        "episode_title": panel.get("title", ""),
        "watched_at": item.get("date_played"),
        "fully_watched": item.get("fully_watched", False),
    }


def parse_episode(e: dict) -> dict:
    """Data de chegada na CR, não a de exibição no Japão: anime antigo que
    entra no catálogo agora é novidade para quem assiste aqui."""
    return {
        "episode_number": _num(e.get("episode_number"), float, None),
        "released_at": e.get("premium_available_date") or e.get("availability_starts")
                       or e.get("episode_air_date"),
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

    # item sem panel: os ids ficam no nível do item e não podem ser perdidos
    sem_panel = parse_history_item(
        {"id": "GYNVQMDGR", "parent_id": "G6GG91P26", "parent_type": "series",
         "date_played": "2025-11-16T14:55:32Z", "fully_watched": True},
        series_title="Food Wars!",
    )
    assert sem_panel["episode_id"] == "GYNVQMDGR"
    assert sem_panel["series_id"] == "G6GG91P26"
    assert sem_panel["series_title"] == "Food Wars!"
    # sem panel não se inventa posição: T1E0 viraria episódio assistido fantasma
    assert sem_panel["season_number"] is None and sem_panel["episode_number"] is None

    ep = parse_episode({"episode_number": 25, "episode_air_date": "2020-01-01T00:00:00Z",
                        "premium_available_date": "2026-04-02T15:00:00Z"})
    assert ep == {"episode_number": 25.0, "released_at": "2026-04-02T15:00:00Z"}
    assert parse_episode({"episode_number": None})["episode_number"] is None

    print("ok")
