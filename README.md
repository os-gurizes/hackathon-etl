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
uv run vstats abilities                    # habilidades e combos (estimativas)
uv run vstats insights                     # textos de insight por jogador e time
uv run vstats all <dataset.zip ou pasta>   # pipeline completo (cerca de 1min30)
uv run vstats export-maps mapas/           # SVG de cada mapa para revisão visual
uv run vstats quality                      # relatório de qualidade do último run
uv run vstats migrate
```

Os passos dependem uns dos outros. Depois de um `ingest`, rode os passos seguintes (ou use `vstats all`): o ingest recria os rounds e kills, e `geometry` recria as zonas, o que apaga o heatmap por zona até rodar `heatmap` de novo.

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

## Tabelas principais (schema `analytics`)

| Tabela | Conteúdo |
|---|---|
| `matches`, `rounds`, `kills`, `round_players`, `position_samples` | dados normalizados do dataset |
| `maps`, `zones`, `map_sites` | silhueta SVG, zonas nomeadas e sites |
| `heatmap_cells`, `heatmap_zones` | contadores para heatmap, filtráveis por mapa, etapa, time, jogador, agente e lado |
| `player_match_stats`, `weapon_stats`, `agent_map_stats` | estatísticas clássicas |
| `round_team_economy`, `economy_flags` | economia e decisões econômicas |
| `round_wp_states`, `kill_impact`, `model_runs` | chance de vitória e impacto de cada kill |
| `strategies`, `round_strategy` | setups detectados e taxa de sucesso |
| `player_patterns` | comportamentos repetitivos |
| `pressure_stats`, `rotations` | pressão e rotações |
| `ability_usage`, `ability_kills`, `combos` | habilidades (estimativas) |
| `insights` | textos prontos para o front |
