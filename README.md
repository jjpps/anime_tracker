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
frontend/            (ainda não existe)
```

O backend não expõe HTTP ainda: o CLI e o banco são a interface. Quando o
frontend entrar, `db.py` é a camada que ele consome — nenhuma regra de negócio
vive no `cli.py`.

## Uso

```bash
python -m venv .venv && .venv/bin/pip install -r backend/requirements.txt

export CR_ETP_RT="<cookie etp_rt do crunchyroll.com>"
make sync                      # importa watchlist, histórico e temporadas
make db                        # catálogo local do AniList (opcional)
make match ARGS=--offline      # casa temporadas; sem --offline usa a API
make test
```

Comandos: `sync`, `match`, `review [list|done|confirm|reject]`, `pending`, `stats`.

### Como obter o etp_rt

Logado em crunchyroll.com: DevTools → Application → Cookies → copiar `etp_rt`.
É credencial de sessão — mantenha fora do repositório.

## Estado

- Crunchyroll: funcionando (watchlist, histórico, temporadas com faixa de anos).
- AniList: cliente escrito, **sem validação ao vivo** — a API está retornando
  403 ("temporarily disabled"). O matcher foi calibrado contra o catálogo local,
  que traz os mesmos IDs.
- Escrita na lista do AniList (OAuth): não implementada.
