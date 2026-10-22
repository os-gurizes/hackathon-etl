# Batch 1: ETL e Inteligência de Dados

Pipeline em Python que lê os JSONs de partidas, normaliza tudo em Postgres e calcula as métricas, os modelos e os insights que a API (Batch 2) apenas lê.

## Regras do batch

- Python 3.12, gerenciado com `uv`.
- Nenhuma chamada a APIs externas ou serviços da Riot, nem em build nem em runtime.
- Fonte de dados exclusiva: os arquivos do dataset. Os nomes de agentes, armas e armor vêm de arquivos estáticos versionados em `reference/` (ver seção 3).
- Idempotente: rodar duas vezes produz o mesmo banco. Upsert pela chave `matchId`.
- Determinístico: toda etapa com aleatoriedade usa seed fixa (`SEED = 42`).

## 1. Diagnóstico do dataset

| Item | Valor |
|---|---|
| Arquivos | 336 JSONs, cerca de 194 MB, formato Riot `match-v1` |
| Campeonatos | Rush Series Esquenta (29), Esquenta 2 (26), Inclusivo (13), Univavá C1 a C4 e Fase de Grupos (268) |
| Rounds | 6.618 |
| Kills | cerca de 46.700, cada um com snapshot de posição e direção da mira de todos os vivos |
| Jogadores únicos | 413 |
| Times (slug) | 68 |
| Patches | 12.10 a 13.06 |
| Mapas | Ascent, Lotus, Haven, Split, Sunset, Abyss, Summit, Breeze, Pearl, Fracture |

### Particularidades que o parser precisa tratar

1. **O nome do time existe só no nome do arquivo.** O padrão é `PREFIXO_NUM[letra]_DD-MM-AA_timeA_X_x_Y_timeB_mapa.json`. O lado Red ou Blue é resolvido comparando o placar do nome com `teams[].roundsWon`. Validado em 336 de 336 arquivos.
2. **A letra depois do número identifica o mapa dentro da série.** `001a`, `001b` e `001c` formam uma MD3.
3. **O prefixo e a pasta definem o campeonato e a etapa**: `UNIVAVA_C1` é Univavá, Classificatória 1; `UNIVAVA_G` é a Fase de Grupos.
4. **Observadores** vêm com `teamId = "Neutral"` e `characterId = null` (22 partidas) e devem ser descartados das estatísticas.
5. **`roundResultCode` vazio** em 97 rounds corresponde a `roundResult = "Round timer expired"`, vitória da defesa.
6. **`ability.*Effects` vem sempre `null`.** Não existe uso de habilidade por round, só `stats.abilityCasts` por partida e kills com `damageType = "Ability"`.
7. **As posições só aparecem em eventos**: a cada kill (`playerLocations` com `viewRadians`), no plant e no defuse. Não há rastreamento contínuo.
8. **O jogador muda de time entre campeonatos** (22 casos). O vínculo jogador e time é por partida.
9. **Slugs parecidos podem ser times distintos**: `ceub_octopus` e `ceub_octopus_vulgaris` se enfrentam na partida `UNIVAVA_G_002a`.
10. **`economy.weapon` pode vir vazio** quando o jogador não tem arma no fim da compra.
11. O ID do mapa é interno: `Jam` é Lotus, `Triad` é Haven, `Bonsai` é Split, `Juliett` é Sunset, `Infinity` é Abyss, `Plummet` é Summit, `Foxtrot` é Breeze, `Pitt` é Pearl, `Canyon` é Fracture. Ele bate 100% com o slug do arquivo.

## 2. Estrutura do projeto

```
etl/
  pyproject.toml
  reference/
    valorant-api-13.08.json      snapshot estático de agentes, habilidades, armas, gear e calibração de mapas
    gist-uuids.json              base do gist NotOfficer (fallback)
    overrides.json               lacunas preenchidas à mão
    team-names.json              slug para nome de exibição, editável pelo time
    zone-labels.json             nomes de callout por zona, opcional, editável
  migrations/                    SQL versionado do schema `analytics`
  src/vstats/
    cli.py                       comandos: ingest, derive, model, insights, all
    raw/                         modelos pydantic do JSON bruto e parser de nome de arquivo
    load/                        escrita no Postgres via COPY
    reference/                   resolução de UUID para nome
    geometry/                    normalização de coordenadas, silhuetas e zonas
    metrics/                     estatísticas clássicas
    economy/
    positioning/                 heatmaps, rotações e espaçamento
    models/                      win probability, estratégias e padrões
    insights/                    geração dos textos e evidências
  tests/
    fixtures/                    3 a 5 JSONs reduzidos
```

Dependências: `pydantic`, `polars`, `numpy`, `scipy`, `scikit-learn` (inclui HDBSCAN), `lightgbm`, `shap`, `scikit-image` (contornos), `shapely`, `psycopg[binary]`, `typer`, `pytest`.

## 3. Dados de referência (estáticos)

A prioridade de resolução é **overrides > snapshot valorant-api > gist**.

| Fonte | Cobertura no dataset |
|---|---|
| Snapshot valorant-api 13.08 | 28 de 28 agentes (com função e nome das 4 habilidades), 3 de 3 armors, 20 de 24 armas, calibração (`xMultiplier`, `yMultiplier`, `xScalarToAdd`, `yScalarToAdd`) dos 10 mapas |
| Gist NotOfficer (patch 2.00) | 14 de 28 agentes, 17 de 24 armas, 0 de 3 armors |
| `overrides.json` | lacunas restantes, listadas abaixo |

Lacunas a preencher manualmente, identificadas pelo agente que usa cada ID:

| ID | Usado por | Provável |
|---|---|---|
| `856d9a7e-4b06-dc37-15dc-9d809c37cb90` | Chamber (481 kills) | Headhunter |
| `39099fb5-4293-def4-1e09-2e9080ce7456` | Chamber (42 kills) | Tour de Force |
| `95336ae4-45d4-1032-cfaf-6bad01910607` | Neon (207 kills) | Overdrive |
| `""` em kill com `damageType = Weapon` | Chamber (169 kills) | arma de habilidade do Chamber, a confirmar |

**Pendência:** confirmar nas regras do hackathon se o snapshot da valorant-api pode ser usado. Se não puder, o fallback é gist mais `overrides.json` ampliado (14 agentes e 3 armors a mais). A calibração dos mapas passa então a ser derivada só da extensão das posições (seção 5.1).

Os IDs sem nome resolvido entram como `Desconhecido (<8 primeiros caracteres>)` e aparecem no relatório de qualidade.

## 4. Modelo de dados (schema `analytics`)

O ETL é dono do schema `analytics`. A API é dona do schema `app` (usuários e estratégias) e lê `analytics` sem escrever nele.

### Dimensões
- `tournaments(id, slug, name)`
- `stages(id, tournament_id, slug, name, order)`
- `series(id, stage_id, number, team_a_id, team_b_id, winner_team_id)`
- `teams(id, slug, display_name)`
- `players(id, puuid_hash, game_name, tag_line)`. O `puuid` original não sai do ETL; guardamos o hash SHA-256.
- `agents(id, uuid, name, role, ability_grenade, ability_1, ability_2, ultimate)`
- `weapons(id, uuid, name, category, cost)`
- `maps(id, internal_name, slug, name, x_mult, y_mult, x_add, y_add, silhouette_svg, bounds)`

### Fatos
- `matches(id, match_uuid, series_id, map_id, game_version, started_at, duration_ms, red_team_id, blue_team_id, winner_team_id, red_score, blue_score, source_file)`
- `match_players(match_id, player_id, team_id, agent_id, side_first_half, score, kills, deaths, assists, rounds_played, casts_grenade, casts_1, casts_2, casts_ult)`
- `rounds(id, match_id, number, winner_team_id, winner_side, result_code, plant_site, plant_time_ms, planter_id, defuser_id, defuse_time_ms, plant_x, plant_y)`
- `round_players(round_id, player_id, team_id, side, score, loadout_value, spent, remaining, weapon_id, armor_id, damage_dealt, headshots, bodyshots, legshots, survived)`
- `kills(id, round_id, t_round_ms, t_game_ms, killer_id, victim_id, weapon_id, damage_type, ability_slot, is_secondary_fire, killer_x, killer_y, victim_x, victim_y, distance, is_first_kill, is_trade, traded_within_ms)`
- `kill_assists(kill_id, player_id)`
- `damage_events(round_id, dealer_id, receiver_id, damage, headshots, bodyshots, legshots)`
- `position_samples(id, kill_id, round_id, t_round_ms, player_id, side, x, y, nx, ny, view_rad, zone_id)`. São cerca de 273 mil linhas, uma por jogador vivo com posição registrada em cada kill.

### Derivados (preenchidos pelas etapas 5 a 9)
- `zones`, `heatmap_cells`, `heatmap_zones`
- `player_match_stats`, `player_aggregates`, `agent_aggregates`, `weapon_aggregates`
- `round_economy`, `economy_flags`
- `round_wp_events` (win probability antes e depois de cada kill)
- `strategies`, `round_strategy`
- `pressure_events`, `rotations`
- `ability_proxies`
- `insights(id, scope, scope_id, map_id, side, kind, severity, title, body, metric_value, baseline_value, sample_size, confidence, evidence_round_ids)`
- `data_quality_report`

Todo agregado tem as chaves de filtro `tournament_id`, `stage_id`, `map_id`, `side` e `team_id`, com `NULL` significando "todos". Assim a API faz só `SELECT`, sem cálculo pesado.

## 5. Etapas do pipeline

### 5.1 Geometria: normalização, silhuetas e zonas

1. **Normalização**: `nx = y * x_mult + x_add` e `ny = x * y_mult + y_add`, levando ao espaço 0..1 do minimapa. Se o snapshot não for liberado, a normalização vira min-max por mapa usando os percentis 0,5 e 99,5 das posições.
2. **Silhueta**:
   - grid de ocupação 512x512 com todas as posições do mapa (snapshots de kill, plant e defuse);
   - dilatação e fechamento morfológico;
   - `skimage.measure.find_contours`, simplificado com Douglas-Peucker via shapely;
   - o resultado é exportado como path SVG em `maps.silhouette_svg`.

   É esse o fundo do heatmap e da prancheta do coach.
3. **Sites**: o centróide das `plantLocation` agrupadas por `plantSite` (A, B, C) é usado como rótulo de referência no mapa.
4. **Zonas**: o snapshot de referência traz os callouts oficiais de cada mapa (nome, região e posição). Cada callout vira a semente de um diagrama de Voronoi recortado pela silhueta, e cada posição recebe a zona do callout mais próximo. Os nomes ficam no formato "Árvore A", "Ladrilhos do Meio". Sem callouts (caso o snapshot não seja liberado), o fallback é KMeans com 24 zonas ("Zona 1" a "Zona 24"). O arquivo `zone-labels.json` permite renomear qualquer zona sem reprocessar.

### 5.2 Estatísticas clássicas

Por jogador, partida, mapa, agente e lado:
- **ACS**: `score / rounds`.
- **ADR**: soma de `damage` dividida pelos rounds.
- **K/D, KDA, HS%**: `headshots / (head + body + leg)`.
- **First kill e first death**: o menor `t_round_ms` do round.
- **KAST**: kill, assist, sobreviveu ou foi trocado. Considera-se trocado quando o killer morre em até 5 s.
- **Multikills** (2K a 5K) e **clutches** (1vX vencidos e disputados, X de 1 a 5). A detecção para quando a spike explode ou é desarmada. Num 1v1, os dois jogadores contam como em clutch, como nos sites de estatística.
- **Plants e defuses.**
- **K/D médio por partida**, além de média, mediana e desvio por jogador.

Por agente: pick rate por mapa, win rate, ACS médio e K/D médio. O ranking de "agentes com melhor desempenho" usa a média bayesiana (shrinkage para a média do mapa), para não premiar agentes com 2 partidas.

### 5.3 Armas

Por arma, jogador e mapa:
- kills e kills por round em que a arma foi comprada;
- HS%;
- distância média do kill (euclidiana entre killer e vítima, convertida para metros com o fator do mapa);
- taxa de vitória do round em que o jogador estava com a arma;
- custo por kill.

Curvas de eficácia por faixa de distância (0 a 10 m, 10 a 20 m, 20 a 30 m, acima de 30 m).

### 5.4 Economia

1. **Compra do time por round**, pela soma de `loadout_value` dos 5 jogadores: Pistol (rounds 1 e 13), Eco (abaixo de 6.000), Semi-eco (6.000 a 12.000), Meia compra (12.000 a 20.000), Full buy (20.000 ou mais). Os limites saíram do histograma real: a taxa de vitória salta de cerca de 25% para mais de 55% entre 12 e 14 mil.
2. **Matriz de vitória por tipo de compra** (minha compra contra a do adversário). Cada round do time guarda `expected_win`: a taxa da matriz para aquele confronto, calculada sem o próprio round. Se o confronto tem menos de 10 rounds, usa a taxa geral daquela compra.
3. **Economia média**: loadout, gasto e saldo por time e round, em `round_team_economy`.
4. **Flags** (`economy_flags`, só rounds regulamentares, sem overtime):
   - `broken_economy`: perdeu a meia compra e jogou o round seguinte em eco ou semi-eco (273 casos). `won` e `expected_win` são do round seguinte, com a compra que o time realmente fez. No dataset, a diferença é zero: o time vence o que se espera de um eco. Por isso o flag é descritivo, e o alerta vem da frequência (o time cai nisso mais que a média?), não do custo.
   - `eco_without_damage` e `full_buy_lost_to_eco`: verdadeiros por definição em rounds perdidos, então `won` contra `expected_win` não mede custo. Também são avaliados pela frequência contra a média.
   - `buy_out_of_sync`, `saved_while_team_bought`, `did_not_drop`, `force_after_pistol_loss`: decisões do jogador ou do time, avaliadas por `won` contra `expected_win`. No dataset, nenhuma tem custo positivo relevante.

### 5.5 Posicionamento e heatmap

1. **Células**: grid 64x64 normalizado. Para cada célula e cada combinação de filtros (mapa, lado, time, jogador, agente, campeonato), calcula:
   - **presença**: amostras de posição;
   - **kills**: posição do killer;
   - **mortes**: `victim_location`;
   - **first kills e first deaths**;
   - **K/D local**: `kills / max(mortes, 1)`, com suavização bayesiana pela média do mapa.
2. **Zonas**: as mesmas métricas agregadas por polígono, mais *taxa de troca* (mortes trocadas sobre o total de mortes na zona) e *tempo médio de contato*.
3. **Formato de armazenamento**: esparso, só células com amostra. A suavização gaussiana para exibição fica no front, para o usuário poder ajustar.

## 6. Modelos de machine learning

### 6.1 Win probability por estado do round (base para medir impacto)

- **Unidade**: início do round, plant, e para cada kill dois estados: logo antes (mesmos vivos, relógio do kill) e logo depois. Kills depois do defuse ou da explosão da spike não entram.
- **Features**:
  - vivos de cada lado e a diferença numérica;
  - soma de loadout de cada lado;
  - tempo do round;
  - spike plantada e tempo desde o plant;
  - site;
  - mapa;
  - lado;
  - placar.
- **Modelo**: LightGBM binário com restrições monotônicas (mais vivos ou mais economia nunca reduz a chance do próprio lado) e regularização forte. A calibração isotônica é testada em cross-fitting e só é usada se melhorar o Brier.
- **Validação**: GroupKFold por partida e teste deixando cada campeonato inteiro de fora, com referência mínima a regressão logística só com vivos, economia, plant e tempo. Resultado atual (103.617 estados): Brier OOF 0,1368 contra 0,1408 da referência, e calibração dentro de 2 pontos. Deixando o Univavá de fora (o treino fica com 20% dos dados), o modelo fica um pouco atrás da referência (0,1445 contra 0,1419). Nos demais campeonatos, ganha.
- **Saída**: `round_wp_states` (WP do ataque em cada estado, out-of-fold, para a curva da partida) e `kill_impact` (WP antes e depois de cada kill). O **impacto** de um kill ou de uma morte é o delta de WP. Todos os insights de "piora de desempenho" são medidos em delta de WP ou em rounds perdidos, nunca em K/D isolado.

### 6.2 Estratégias (clustering de setups)

- **Unidade**: round e time.
- **Features**: zona de cada jogador no setup (último snapshot até o segundo kill ou 40 s, incluindo a posição da vítima no momento da morte; jogador sem posição nessa janela fica de fora, para não usar posições de depois do plant), como vetor de ocupação por zona e por região (A, B, C, Meio, Base). O plant **não** entra nas features: usá-lo vazava o resultado (plantar está muito ligado a vencer), e a estratégia tem que refletir a intenção do setup.
- **Modelo**: um clustering por mapa e lado, com PCA seguido de HDBSCAN. Os rounds que ficam como ruído viram "Sem padrão definido". Mapas com menos de 80 rounds por lado não são agrupados (Fracture e Pearl).
- **Descrição automática**: distribuição por região (o arredondamento sempre soma o tamanho do time), zona de foco, site e mediana do tempo de plant naquele site. O site só entra no título se tiver 60% ou mais dos plants; senão o título diz "Ataque dividido entre A e B". Exemplos: "Execução rápida no B pelo Principal B", "Stack de 3 no A, foco em Vigas A".
- **Métricas**: taxa de sucesso com intervalo de Wilson e frequência. O cruzamento ataque contra defesa e o uso por time saem de `round_strategy`.
- **Saída**: `strategies` e `round_strategy`.

### 6.3 Comportamentos repetitivos que pioram o desempenho

Por jogador, mapa e lado (mínimo de 15 rounds):

| Padrão | Definição | Base de comparação |
|---|---|---|
| `first_death_zone` | morre primeiro do round na mesma zona com frequência | taxa de first death naquela zona, mapa e lado |
| `isolated_death` | morte sem aliado a 15 m e sem troca | mesma função, mapa e lado |
| `repeat_after_first_death` | morre primeiro na mesma zona no round seguinte | taxa da zona no mapa e lado |
| `predictable_route` | entropia da zona no início do round entre os 10% mais baixos da função, com first deaths acima da média | taxa de first death do mapa e lado |

- **Significância**: teste binomial unilateral, com correção de Benjamini-Hochberg sobre **todos** os testes elegíveis (inclusive zonas e jogadores sem nenhuma ocorrência, que entram com p = 1). O mínimo de 3 ocorrências só filtra o que é exibido. Dois níveis em `tier`:
  - `confirmed`: p ajustado abaixo de 0,1, acima do esperado e custo positivo. No dataset, 2 padrões.
  - `watch` ("padrão a observar"): p bruto abaixo de 0,01, pelo menos 1,5 vez o esperado e custo de meio round ou mais. No dataset, 76. A interface mostra como indício, não como fato. Com 5 a 15 partidas por jogador e mapa, poucos padrões individuais passam numa correção estrita.
- **Rota previsível**: entropia da zona do setup (até 40 s, incluindo a posição da vítima), normalizada pelo número de zonas do mapa.
- **Custo** (`cost_rounds`): ocorrências acima do esperado vezes a perda média de chance de vitória (do modelo 6.1) nesses eventos. A unidade é rounds.
- Foi usado no lugar do LightGBM com SHAP previsto antes: é mais simples de explicar ("isso custa 1,5 round") e cada padrão tem a evidência dos rounds de exemplo.
- **Saída**: `player_patterns`, com os rounds de exemplo em `evidence_round_ids`.

### 6.4 Tendências sob pressão

Contextos de pressão marcados por round:
- desvantagem numérica;
- pós-plant;
- clutch 1vX;
- menos de 20 s no relógio;
- sequência de 3 ou mais rounds perdidos;
- match point de qualquer lado;
- eco contra full buy.

Métricas por contexto contra a referência do próprio jogador: K/D, primeira ação, sobrevivência e delta de WP.

**Rotações** (`rotations`):
- **Detecção**: o jogador é visto num site e depois em outro (passar pelo Meio conta), comparando com o último site em que foi visto.
- **Rotação sem informação**: quando ele saiu, ainda não tinha havido kill (de qualquer time) nem plant no site de destino. É o exemplo de "recuar de um bomb sem certeza de inimigo no outro".
- **Resultado medido**: o site abandonado recebeu plant depois que o jogador saiu? Também a vitória do round. No dataset, na defesa, o site abandonado cai 2,3 vezes mais nas rotações sem informação (7,8% contra 3,4%). A vitória do round não segue a mesma direção, porque as rotações com informação acontecem quando o time já está sob pressão; por isso a métrica principal é o site abandonado.
- **Limitação**: as amostras de posição só existem em momentos de kill, então a rotação é detectada com atraso. A UI informa isso.

**Decisões de clutch**:
- **Classificação**: salvou (vivo no fim, round perdido, longe da spike), lutou ou tentou o defuse.
- **Métrica**: taxa de acerto da decisão, contra a WP estimada no momento.

### 6.5 Habilidades (proxies, sempre marcados como estimativa)

Como `abilityEffects` vem nulo, todo indicador de habilidade é aproximado e leva `is_estimate = true`.

- **Kills por habilidade**: `damage_type = Ability` e `ability_slot`, com o nome da habilidade vindo da referência do agente (por exemplo, "Showstopper").
- **Combos com aliados**:
  - **Pares**: assistente A e killer B na mesma kill.
  - **Sequências**: kill de habilidade de A seguida de kill de B em até 3 s, ou assist de um iniciador (Sova, Fade, Skye, KAY/O, Breach, Gekko, Tejo) seguido de um kill.
  - **Métricas**: frequência, delta de WP médio e conversão em plant ou retake no mesmo round ("domínio de bomb").
  - **Ranking**: pares de agentes e de jogadores.
- **Uso sem necessidade (estimado)**:
  - casts por round da partida acima do percentil 80 do agente no mapa, sem aumento correspondente de kills, assists ou WP;
  - ultimates gastas em rounds com WP já acima de 0,85 ou abaixo de 0,1, quando o round tem kill de ultimate.

  Isso é uma regressão por partida, não por round, e a UI deve dizer isso explicitamente.

## 7. Geração de insights

Cada modelo grava linhas em `insights` com:
- `kind`: `repetitive_pattern`, `economy`, `pressure`, `rotation`, `ability_estimate`, `strategy`, `weapon`, `agent`;
- `severity` de 1 a 3, a partir do impacto em WP e da confiança;
- `title` e `body` em português, escritos para leigos. Exemplo: "No Lotus, ao atacar, você morre primeiro no Mid A em 38% dos rounds. A média dos jogadores é 14%. Isso custa em média 0,6 round por mapa.";
- `evidence_round_ids`, para o front poder abrir os rounds de exemplo.

Os textos seguem templates fixos em `insights/templates.py`, sem LLM, com números arredondados e sem jargão estatístico (nada de "p-valor" na frase).

## 8. Qualidade e validação

- Relatório `data_quality_report`: arquivos ignorados, IDs sem nome, partidas com observador, rounds sem código e divergências de placar.
- Testes:
  - parser de nome de arquivo, todos os prefixos, incluindo `014a` e `014b`;
  - resolução de lado Red e Blue;
  - KAST, trade e first kill em fixture com valores calculados à mão;
  - classificação de compra;
  - normalização de coordenadas, com os sites caindo dentro da silhueta;
  - ingestão repetida sem duplicar dados.
- Sanidade: a soma das kills por jogador em `kills` é igual a `match_players.kills` em todas as partidas.
- Modelos: as métricas de validação são registradas em `analytics.model_runs` (versão, data, métricas, seed).

## 9. Entregáveis e critérios de aceite

| # | Entrega | Aceite |
|---|---|---|
| 1 | `vstats ingest <pasta-ou-zip>` | 336 partidas carregadas, relatório de qualidade sem divergência de placar |
| 2 | Referências resolvidas | 100% dos agentes e armors com nome; armas com no máximo os 4 IDs do override pendentes |
| 3 | Silhuetas e zonas dos 10 mapas | SVG válido, sites A, B (e C) dentro do contorno, de 20 a 40 zonas por mapa |
| 4 | Estatísticas clássicas e de armas | conferem com `players[].stats` (kills, deaths, assists, score) |
| 5 | Economia e flags | histograma de loadout revisado e limites ajustados |
| 6 | Win probability | Brier melhor que a referência logística no campeonato deixado de fora |
| 7 | Estratégias, padrões, pressão e proxies de habilidade | tabelas preenchidas, cada linha com `sample_size` e `confidence` |
| 8 | `insights` | ao menos 1 insight por jogador com 5 ou mais partidas |
| 9 | `vstats all` | pipeline completo em menos de 10 min numa máquina comum |

## 10. Ordem de execução sugerida

1. Parser, schema, ingestão e qualidade (entregas 1 e 2). Isso destrava o Batch 2.
2. Geometria e heatmap (3). Isso destrava as telas de mapa do Batch 3.
3. Estatísticas, armas e economia (4 e 5).
4. Win probability (6).
5. Estratégias, padrões, pressão e habilidades (7).
6. Insights (8) e otimização (9).

## Contrato com o Batch 2

- O schema `analytics` é publicado em `migrations/` e não muda sem bump de versão.
- A API gera os tipos Drizzle com `drizzle-kit pull` apenas desse schema.
- Toda tabela derivada tem uma coluna `pipeline_version`.
