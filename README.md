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

cp .env.example .env        # e preencha com os valores reais
make sync                      # importa watchlist, histórico e temporadas
make db                        # catálogo local do AniList (opcional)
make match ARGS=--offline      # casa temporadas; sem --offline usa a API
make test
```

make serve                     # http://localhost:8000
```

Depois de subir, o resto é pela UI: **Sincronizar** importa da Crunchyroll e
**Conectar AniList** faz o OAuth. Os comandos de terminal existem para uso
automatizado; no dia a dia não são necessários.

Comandos: `sync`, `match`, `review [list|done|confirm|reject]`, `pending`,
`stats`, `serve`.

### Rate limit do AniList

O cliente segue os headers em vez de um intervalo fixo: `X-RateLimit-Limit`
define o espaçamento (60/limite segundos entre chamadas), então ele se adapta
sozinho aos 90/min normais e aos 30/min do estado degradado atual. Num 429,
espera o `Retry-After` — ou o `X-RateLimit-Reset`, ou 60s — e repete no máximo
3 vezes antes de desistir, para um 429 permanente não prender a thread do
servidor.

Na UI, dois botões: **Sincronizar** (Crunchyroll + match) e **Casar com
AniList** (só o match, sem tocar na CR). Só uma tarefa roda por vez, e o
progresso aparece no próprio botão. Os logs do AniList saem no console do
servidor (`anime_tracker.anilist`, `anime_tracker.sync`,
`anime_tracker.catalog`).

## Sync incremental

`sync` (ou o botão **Sincronizar** na UI) traz só o que mudou:

1. **histórico** — a CR devolve ordenado por `date_played` desc, então o
   percurso para ao cruzar a data do episódio mais recente já gravado (com 1
   dia de folga). ~50 páginas viram 1-2.
2. **escopo** — watchlist ∪ séries distintas do histórico (145 hoje),
   resolvidas em lote via `cms/objects`: 3 chamadas trazem
   `episode_count`/`season_count` de todas.
3. **temporadas** — só rebuscadas se a série nunca sincronizou ou se a
   contagem mudou. Episódio novo incrementa `episode_count`, então estreia é
   detectada sem custo extra. É a parte cara: 1 chamada por temporada.

`season.is_complete` da CR **não** serve como sinal: vem `False` até para
temporada encerrada há anos.

Intervalo mínimo entre syncs: 6h (`SYNC_TTL_HORAS`), com `--force` / confirmação
na UI para ignorar.

### Windows (PowerShell)

Não há `make` no Windows; os comandos equivalentes:

```powershell
python -m venv .venv
.venv\Scripts\pip install -r backend\requirements.txt

copy .env.example .env      # e preencha com os valores reais

.venv\Scripts\python run.py sync
.venv\Scripts\python run.py match
.venv\Scripts\python run.py serve
```

`run.py` roda da raiz do repositório. O equivalente sem ele é
`cd backend` e `python -m anime_tracker <comando>` — a raiz do repo e o pacote
têm o mesmo nome, então `python -m anime_tracker` na raiz acha a pasta e falha
com `No module named anime_tracker`.

O `.env` é lido automaticamente; não precisa exportar nada. Uma variável
definida no shell sobrepõe o arquivo, se você quiser trocar um valor pontual.

## AniList OAuth

Em anilist.co/settings/developer, crie uma aplicação com a Redirect URL
`http://localhost:8000/auth/anilist/callback` (idêntica à do `.env`) e preencha
`ANILIST_CLIENT_ID` e `ANILIST_CLIENT_SECRET`. O client id é um inteiro curto e
não é secreto; o secret é.

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
