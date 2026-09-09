"""Integração com o MyAnimeList: resolve mal_id e confere contra a API deles.

Desenho deliberado: **nada de busca por título**. O mal_id vem do catálogo
local, que cruza anilist_id e mal_id, e a API é usada só para buscar POR ID.
Motivos concretos:
  - a busca do MAL rejeita `q` longo com 400 ("invalid q"), e títulos da
    Crunchyroll passam fácil de 64 caracteres;
  - a busca do Jikan está devolvendo 504, enquanto a busca por id responde 200;
  - buscar por título é justamente o passo que erra, e é o que a tela de
    revisão existe para corrigir. Reintroduzi-lo aqui seria repetir o problema.

Duas fontes, mesma interface:
  - API oficial (api.myanimelist.net) quando MAL_CLIENT_ID está no ambiente;
  - Jikan (api.jikan.moe), não-oficial e sem autenticação, como alternativa.
"""

import logging
import time

import requests

log = logging.getLogger("anime_tracker.mal")

MAL_API = "https://api.myanimelist.net/v2"
JIKAN_API = "https://api.jikan.moe/v4"
# Jikan pede no máximo 3 req/s e 60/min; 1s por chamada fica dentro dos dois
INTERVALO_JIKAN = 1.0
INTERVALO_OFICIAL = 0.3
MAX_TENTATIVAS = 3


class MALError(Exception):
    pass


class MALClient:
    """Busca anime por id. Usa a API oficial se houver client id; senão Jikan."""

    def __init__(self, client_id=None, session=None):
        self.client_id = client_id or ""
        self.oficial = bool(self.client_id)
        self.session = session or requests.Session()
        self.session.headers.update({
            "User-Agent": "anime-tracker/0.1",
            "Accept": "application/json",
        })
        if self.oficial:
            self.session.headers["X-MAL-CLIENT-ID"] = self.client_id
        self.intervalo = INTERVALO_OFICIAL if self.oficial else INTERVALO_JIKAN
        self._proxima = 0.0
        log.info("fonte MAL: %s", "API oficial" if self.oficial else "Jikan (sem auth)")

    @property
    def fonte(self):
        return "myanimelist" if self.oficial else "jikan"

    def anime(self, mal_id, tentativa=1):
        """(título, episódios) ou None se o id não existe lá."""
        atraso = self._proxima - time.monotonic()
        if atraso > 0:
            time.sleep(atraso)

        url = (f"{MAL_API}/anime/{mal_id}?fields=title,num_episodes" if self.oficial
               else f"{JIKAN_API}/anime/{mal_id}")
        resp = self.session.get(url, timeout=30)
        self._proxima = time.monotonic() + self.intervalo

        if resp.status_code == 404:
            log.warning("id %s não existe no MAL", mal_id)
            return None
        if resp.status_code == 429 or resp.status_code >= 500:
            # 5xx entra aqui porque o Jikan devolve 504 sob carga, e insistir
            # depois de uma pausa costuma resolver
            if tentativa >= MAX_TENTATIVAS:
                raise MALError(f"id {mal_id}: {resp.status_code} após {tentativa} tentativas")
            espera = int(resp.headers.get("Retry-After", 5)) * tentativa
            log.warning("id %s: HTTP %s, aguardando %ds (tentativa %d/%d)",
                        mal_id, resp.status_code, espera, tentativa, MAX_TENTATIVAS)
            time.sleep(espera)
            return self.anime(mal_id, tentativa + 1)
        if not resp.ok:
            raise MALError(f"id {mal_id}: HTTP {resp.status_code} {resp.text[:120]}")

        dados = resp.json()
        if not self.oficial:
            dados = dados.get("data", {})
        titulo = dados.get("title")
        episodios = dados.get("num_episodes") if self.oficial else dados.get("episodes")
        return titulo, episodios


def resolver_ids(conn, mapa, progresso=None):
    """Preenche mal_id a partir do anilist_id, usando o catálogo local."""
    from . import db

    aviso = progresso or (lambda *a, **k: None)
    faltando = conn.execute(
        "SELECT season_id, anilist_id FROM matches "
        "WHERE anilist_id IS NOT NULL AND mal_id IS NULL"
    ).fetchall()

    pares = []
    sem_mapa = 0
    for i, r in enumerate(faltando, 1):
        aviso("resolvendo ids do MAL", i, len(faltando))
        achado = mapa.get(r["anilist_id"])
        if achado:
            status = achado[4] if len(achado) > 4 else None
            pares.append((r["season_id"], achado[0], status))
        else:
            sem_mapa += 1
    db.set_mal_ids(conn, pares)
    log.info("mal_id resolvido para %d temporada(s); %d sem correspondência", len(pares), sem_mapa)
    return {"resolvidos": len(pares), "sem_mapa": sem_mapa}


def _divergencia(linha, titulo_mal, episodios_mal):
    """Por que essa linha merece olho humano, ou None se está coerente."""
    if titulo_mal is None:
        return "id não existe no MyAnimeList"
    nossos = linha["anilist_episodes"]
    if nossos and episodios_mal and nossos != episodios_mal:
        return f"episódios divergem: AniList {nossos} x MAL {episodios_mal}"
    if episodios_mal and linha["cr_episodes"] > episodios_mal:
        # a CR junta o que o MAL separa; o progresso vai ser limitado no export
        return f"CR tem {linha['cr_episodes']} eps e a obra no MAL tem {episodios_mal}"
    return None


def double_check(conn, cliente, limite=None, revalidar=False, progresso=None):
    """Confere cada mal_id contra a API do MAL e aponta o que não bate.

    Não corrige nada sozinho: divergência vira relatório, porque escolher entre
    duas fontes que discordam é decisão de quem revisa."""
    from . import db

    aviso = progresso or (lambda *a, **k: None)
    # colunas explícitas: `total_episodes` existe em series e em seasons, e o
    # SELECT * deixaria ambíguo qual venceu
    sql = ("SELECT m.season_id, m.mal_id, m.anilist_title, m.anilist_episodes, "
           "       s.season_number, s.total_episodes AS cr_episodes, "
           "       se.title AS series_title "
           "  FROM matches m JOIN seasons s USING (season_id) "
           "  JOIN series se USING (series_id) WHERE m.mal_id IS NOT NULL")
    if not revalidar:
        sql += " AND m.mal_checked_at IS NULL"
    sql += " ORDER BY se.title, s.season_number"
    linhas = conn.execute(sql).fetchall()
    if limite:
        linhas = linhas[:limite]

    relatorio = {"checados": 0, "divergentes": [], "erros": [], "fonte": cliente.fonte}
    for i, linha in enumerate(linhas, 1):
        aviso(f"conferindo {linha['series_title']}", i, len(linhas))
        try:
            resposta = cliente.anime(linha["mal_id"])
        except MALError as e:
            relatorio["erros"].append({"season_id": linha["season_id"], "erro": str(e)})
            continue

        titulo_mal, episodios_mal = resposta if resposta else (None, None)
        db.set_mal_check(conn, linha["season_id"], titulo_mal, episodios_mal)
        relatorio["checados"] += 1

        motivo = _divergencia(linha, titulo_mal, episodios_mal)
        if motivo:
            relatorio["divergentes"].append({
                "season_id": linha["season_id"],
                "serie": linha["series_title"],
                "temporada": linha["season_number"],
                "anilist": linha["anilist_title"],
                "mal": titulo_mal,
                "mal_id": linha["mal_id"],
                "motivo": motivo,
            })
    return relatorio
