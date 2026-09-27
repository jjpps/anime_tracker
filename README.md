# anime_tracker

Mostra o que saiu na Crunchyroll dos animes que você já começou: **temporada
nova** e **continuação** (a parte seguinte que a CR anexa na mesma temporada).
A CR só avisa episódios de temporadas recentes; o que sai um ou dois anos
depois não chega até você por ela.

Os termos estão no [CONTEXT.md](CONTEXT.md); a saída do AniList/MAL, em
[docs/adr/0001](docs/adr/0001-crunchyroll-como-unica-fonte.md).

## Estrutura

```
backend/anime_tracker/
  crunchyroll.py   cliente da API da CR (auth por cookie etp_rt, histórico, temporadas, episódios)
  sync.py          sync incremental e registro da última falha
  novidades.py     a regra: temporada nova e continuação
  db.py            schema e acesso ao SQLite
  cli.py           comandos
  server.py        Flask: frontend e API
frontend/web/      Angular: a lista de novidades
```

## Uso

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt
cp .env.example .env           # e preencha o CR_ETP_RT
(cd frontend/web && npm install && npm run build)

make sync                      # busca histórico, temporadas e episódios
make novidades                 # a lista no terminal
make serve                     # http://localhost:8000
make test
```

No Windows, sem `make`: `.venv\Scripts\python run.py crunchyroll`,
`... run.py novidades`, `... run.py serve`.

### Sync diário (cron)

A lista só serve se o sync rodar sem você lembrar:

```cron
0 9 * * * cd /caminho/do/anime_tracker && .venv/bin/python run.py crunchyroll
```

Se falhar (normalmente o cookie expirado), a tela mostra o erro no topo até o
próximo sync dar certo.

### Como obter o etp_rt

Logado em crunchyroll.com: DevTools → Application → Cookies → copiar `etp_rt`.
É credencial de sessão, mantenha fora do repositório. Ele expira; quando o sync
falhar com `invalid_grant`, copie de novo.

## Sync incremental

1. **histórico**: a CR devolve ordenado por `date_played` desc, então o
   percurso para ao cruzar a data do episódio mais recente já gravado (com 1
   dia de folga).
2. **escopo**: as séries distintas do histórico, resolvidas em lote via
   `cms/objects`, que traz `episode_count`/`season_count` de todas.
3. **temporadas e episódios**: só rebuscados se a série ainda não tem
   episódios gravados ou se a contagem mudou. Episódio novo incrementa
   `episode_count`, então temporada nova e continuação são detectadas sem custo
   extra. É a parte cara: 1 chamada por temporada.

Intervalo mínimo entre syncs: 6h (`SYNC_TTL_HORAS`), com `--force` ou
confirmação na UI para ignorar.

## Limites conhecidos

- A CR não marca o que é extra (filme, OVA, especial). A regra vai pelo título,
  então extra com nome sem essas palavras (ex.: "Narumi's Week at Work") aparece
  como temporada nova.
- Episódio do histórico sem temporada (item sem `panel`, conteúdo tirado do
  catálogo) não entra na conta.
