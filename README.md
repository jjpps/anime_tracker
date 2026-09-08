# anime_tracker

Acompanhamento de anime cruzando o histórico da Crunchyroll com o catálogo do AniList.

## Estrutura

```
backend/
  anime_tracker/
    crunchyroll.py   cliente da API da CR (auth por cookie etp_rt, watchlist, histórico)
    anilist.py       cliente da API do AniList + matcher temporada -> obra
    catalog.py       catálogo local do AniList, mesma interface do cliente da API
    progress.py      cálculo do que falta assistir
    db.py            schema e acesso ao SQLite
    cli.py           comandos
  tests/
    oauth.py         OAuth do AniList (authorization code + callback)
    server.py        Flask: frontend, API de revisão e callback
  tests/
frontend/
  index.html         dois menus: catálogo sincronizado e catálogo a revisar
```

Nenhuma regra de negócio vive em `cli.py` nem em `server.py`: os dois leem de
`db.py`. O frontend é HTML e JS puros, sem build.

## Uso

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt

export CR_ETP_RT="<cookie etp_rt do crunchyroll.com>"
make sync                      # importa watchlist, histórico e temporadas
make db                        # catálogo local do AniList (opcional)
make match ARGS=--offline      # casa temporadas; sem --offline usa a API
make test
```

make serve                     # http://localhost:8000
```

Comandos: `sync`, `match`, `review [list|done|confirm|reject]`, `pending`,
`stats`, `serve`.

### Windows (PowerShell)

Não há `make` no Windows; os comandos equivalentes:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt

$env:CR_ETP_RT = "<cookie etp_rt>"
$env:ANIME_TRACKER_DB = "$PWD\anime_tracker.db"

cd backend
..\.venv\Scripts\python -m anime_tracker sync
..\.venv\Scripts\python -m anime_tracker match
..\.venv\Scripts\python -m anime_tracker serve
```

As variáveis valem só para o terminal aberto; para persistir use
`setx CR_ETP_RT "..."` e abra um terminal novo.

## AniList OAuth

Em anilist.co/settings/developer, crie uma aplicação com a Redirect URL
`http://localhost:8000/auth/anilist/callback` e exporte:

```bash
export ANILIST_CLIENT_ID=...
export ANILIST_CLIENT_SECRET=...
```

Depois "Conectar AniList" no topo da página. O token vale 1 ano, não há refresh
token e não há scopes — ele dá acesso quase total à conta e fica no SQLite, que
por isso está no .gitignore.

### Como obter o etp_rt

Logado em crunchyroll.com: DevTools → Application → Cookies → copiar `etp_rt`.
É credencial de sessão — mantenha fora do repositório.

## Estado

- Crunchyroll: funcionando (watchlist, histórico, temporadas com faixa de anos).
- AniList: cliente escrito, **sem validação ao vivo** — a API está retornando
  403 ("temporarily disabled"). O matcher foi calibrado contra o catálogo local,
  que traz os mesmos IDs.
- OAuth: implementado, **sem validação ao vivo** pelo mesmo 403.
- Escrita na lista do AniList: não implementada.
