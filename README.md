# vstats ETL

Ingestão e análise das partidas. O planejamento completo está em `docs/plano.md`.

## Setup

```
uv sync
createdb vstats
```

`VSTATS_DATABASE_URL` define o banco (padrão `postgresql:///vstats`).

## Comandos

```
uv run vstats ingest <dataset.zip ou pasta>   # pode repetir sem duplicar
uv run vstats geometry                     # silhueta, sites e zonas; rodar depois de cada ingest
uv run vstats heatmap                      # agrega presença, kills e mortes por célula e zona
uv run vstats stats                        # ACS, ADR, KAST, clutches, armas e agentes
uv run vstats economy                      # tipo de compra por round e flags econômicos
uv run vstats win-probability              # modelo de chance de vitória e impacto de cada kill
uv run vstats strategies                   # setups de ataque e defesa agrupados por mapa e lado
uv run vstats patterns                     # comportamentos repetitivos por jogador
uv run vstats pressure                     # desempenho sob pressão e rotações
uv run vstats all <dataset.zip ou pasta>   # pipeline completo
uv run vstats export-maps mapas/           # SVG de cada mapa para revisão visual
uv run vstats quality                      # relatório de qualidade do último run
uv run vstats migrate
```

## Testes

```
createdb vstats_test
uv run pytest
```

Os testes marcados com `db` usam `VSTATS_TEST_DATABASE_URL` (padrão `postgresql:///vstats_test`) e são pulados se o banco não existir.

## Referências estáticas (`reference/`)

| Arquivo | Uso |
|---|---|
| `valorant-api-13.08.json` | agentes, habilidades, armas, armor, calibração e callouts dos mapas |
| `gist-uuids.json` | fallback de nomes |
| `overrides.json` | lacunas preenchidas à mão; tem prioridade sobre as outras fontes |
| `team-names.json` | nome de exibição de cada time; editar à vontade e rodar o ingest de novo |
| `zone-labels.json` | renomear zonas, por mapa: `{"Ascent": {"A/Árvore": "Tree A"}}` |
