# Notícias

As principais manchetes dos jornais do mundo inteiro, reunidas num só lugar —
organizadas por região, com os assuntos que mais se repetem entre os jornais.

**Site:** https://fernandalpcosta.github.io/noticias/

## Como funciona

- `scripts/feeds.json` — a lista de jornais (nome, país, idioma, região e endereço do feed RSS).
- `scripts/fetch_news.py` — busca as manchetes e grava `data/news.json`.
- `.github/workflows/atualizar.yml` — roda o script sozinho **a cada 3 horas** e salva a nova edição.
- `index.html` + `assets/` — a página, que lê o `data/news.json`.

Para atualizar na hora: aba **Actions** → *Atualizar manchetes* → **Run workflow**.

## Adicionar ou tirar um jornal

Edite `scripts/feeds.json`. Cada jornal é uma linha assim:

```json
{ "name": "Nome do jornal", "country": "País", "lang": "pt", "region": "brasil", "url": "https://endereco-do-feed-rss" }
```

As regiões disponíveis estão no topo do mesmo arquivo.

## Resumo do dia (opcional)

Se você criar o secret `ANTHROPIC_API_KEY` (Settings → Secrets and variables → Actions),
o script pede ao Claude um **Resumo do dia** em português com os 6–8 assuntos mais
importantes, que aparece no topo do portal. Sem a chave, o portal funciona normalmente,
só sem esse bloco.

## Rodar no computador

```bash
python3 scripts/fetch_news.py
python3 -m http.server
# abra http://localhost:8000
```
