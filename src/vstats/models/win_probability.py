import json
from collections import defaultdict
from dataclasses import dataclass

import lightgbm as lgb
import numpy as np
import psycopg
from numpy.typing import NDArray
from sklearn.isotonic import IsotonicRegression
from sklearn.linear_model import LogisticRegression
from sklearn.metrics import brier_score_loss, log_loss, roc_auc_score
from sklearn.model_selection import GroupKFold

from vstats.config import PIPELINE_VERSION

SEED = 42
FOLDS = 5
SITES = {"A": 1, "B": 2, "C": 3}
FEATURES = (
    "attack_alive", "defense_alive", "alive_diff", "attack_loadout", "defense_loadout", "loadout_diff",
    "t_round_s", "planted", "t_since_plant_s", "plant_site", "map_id", "is_pistol", "attack_score", "defense_score",
)
BASELINE_FEATURES = ("alive_diff", "loadout_diff", "planted", "t_round_s")
CATEGORICAL = ("plant_site", "map_id")
MONOTONE = {"attack_alive": 1, "defense_alive": -1, "alive_diff": 1, "attack_loadout": 1, "defense_loadout": -1, "loadout_diff": 1}
PARAMS = {
    "n_estimators": 300,
    "learning_rate": 0.03,
    "num_leaves": 15,
    "min_child_samples": 200,
    "reg_lambda": 5.0,
    "monotone_constraints": [MONOTONE.get(name, 0) for name in FEATURES],
    "subsample": 0.8,
    "subsample_freq": 1,
    "colsample_bytree": 0.8,
    "random_state": SEED,
    "deterministic": True,
    "n_jobs": 4,
    "verbose": -1,
}

ROUNDS_SQL = """
    SELECT r.id, r.match_id, st.tournament_id, m.map_id, r.number, r.attack_team_id, r.defense_team_id, r.winner_side,
           r.plant_time_ms, r.plant_site,
           sum(rp.loadout_value) FILTER (WHERE rp.side = 'attack'),
           sum(rp.loadout_value) FILTER (WHERE rp.side = 'defense'),
           count(*) FILTER (WHERE rp.side = 'attack'),
           count(*) FILTER (WHERE rp.side = 'defense')
    FROM analytics.rounds r
    JOIN analytics.matches m ON m.id = r.match_id
    JOIN analytics.series s ON s.id = m.series_id
    JOIN analytics.stages st ON st.id = s.stage_id
    JOIN analytics.round_players rp ON rp.round_id = r.id
    GROUP BY r.id, r.match_id, st.tournament_id, m.map_id
    ORDER BY r.match_id, r.number
"""

KILLS_SQL = """
    SELECT k.round_id, k.id, k.t_round_ms, rp.side
    FROM analytics.kills k
    JOIN analytics.round_players rp ON rp.round_id = k.round_id AND rp.player_id = k.victim_id
    ORDER BY k.round_id, k.seq
"""


@dataclass(frozen=True, slots=True)
class State:
    round_id: int
    seq: int
    event: str
    kill_id: int | None
    t_round_ms: int
    attack_alive: int
    defense_alive: int


@dataclass
class Dataset:
    states: list[State]
    features: NDArray[np.float64]
    label: NDArray[np.int64]
    groups: NDArray[np.int64]
    tournaments: NDArray[np.int64]


def build_dataset(conn: psycopg.Connection) -> Dataset:
    kills: dict[int, list[tuple[int, int, str]]] = defaultdict(list)
    for round_id, kill_id, t, victim_side in conn.execute(KILLS_SQL):
        kills[round_id].append((kill_id, t, victim_side))

    states: list[State] = []
    rows: list[list[float]] = []
    labels: list[int] = []
    groups: list[int] = []
    tournaments: list[int] = []
    score: dict[tuple[int, int], int] = defaultdict(int)
    for (round_id, match_id, tournament_id, map_id, number, attack_team, defense_team, winner_side, plant_time, plant_site,
         attack_loadout, defense_loadout, attack_players, defense_players) in conn.execute(ROUNDS_SQL).fetchall():
        events: list[tuple[int, int, str, int | None, str | None]] = [
            (t, 1, "kill", kill_id, side) for kill_id, t, side in kills[round_id]
        ]
        if plant_time is not None:
            events.append((plant_time, 0, "plant", None, None))
        events.sort(key=lambda e: (e[0], e[1]))

        attack_score = score[(match_id, attack_team)]
        defense_score = score[(match_id, defense_team)]
        alive = {"attack": attack_players, "defense": defense_players}
        planted_at: int | None = None
        timeline: list[tuple[str, int | None, int]] = [("start", None, 0)]
        timeline_alive = [(alive["attack"], alive["defense"], None)]
        for t, _, event, kill_id, victim_side in events:
            if event == "plant":
                planted_at = t
            elif victim_side is not None:
                alive[victim_side] = max(alive[victim_side] - 1, 0)
            timeline.append((event, kill_id, t))
            timeline_alive.append((alive["attack"], alive["defense"], planted_at))

        for seq, ((event, kill_id, t), (att, dfn, planted)) in enumerate(zip(timeline, timeline_alive, strict=True)):
            states.append(State(round_id, seq, event, kill_id, t, att, dfn))
            rows.append([
                att, dfn, att - dfn, attack_loadout, defense_loadout, attack_loadout - defense_loadout,
                t / 1000, float(planted is not None), (t - planted) / 1000 if planted is not None else 0.0,
                SITES.get(plant_site or "", 0) if planted is not None else 0, map_id,
                float(number in (0, 12)), attack_score, defense_score,
            ])
            labels.append(int(winner_side == "attack"))
            groups.append(match_id)
            tournaments.append(tournament_id)

        score[(match_id, attack_team if winner_side == "attack" else defense_team)] += 1

    return Dataset(
        states,
        np.array(rows, dtype=np.float64),
        np.array(labels, dtype=np.int64),
        np.array(groups, dtype=np.int64),
        np.array(tournaments, dtype=np.int64),
    )


def _model() -> lgb.LGBMClassifier:
    return lgb.LGBMClassifier(**PARAMS)


def _fit(model: lgb.LGBMClassifier, x: NDArray[np.float64], y: NDArray[np.int64]) -> lgb.LGBMClassifier:
    categorical = [FEATURES.index(name) for name in CATEGORICAL]
    return model.fit(x, y, categorical_feature=categorical)


def _metrics(y: NDArray[np.int64], p: NDArray[np.float64]) -> dict[str, float]:
    clipped = np.clip(p, 1e-6, 1 - 1e-6)
    return {
        "brier": round(float(brier_score_loss(y, clipped)), 4),
        "log_loss": round(float(log_loss(y, clipped)), 4),
        "auc": round(float(roc_auc_score(y, clipped)), 4),
    }


def _baseline_columns(x: NDArray[np.float64]) -> NDArray[np.float64]:
    return x[:, [FEATURES.index(name) for name in BASELINE_FEATURES]]


def out_of_fold(data: Dataset) -> tuple[NDArray[np.float64], NDArray[np.float64], NDArray[np.int64]]:
    model_pred = np.zeros(len(data.label))
    baseline_pred = np.zeros(len(data.label))
    fold_of = np.zeros(len(data.label), dtype=np.int64)
    for fold, (train, test) in enumerate(GroupKFold(n_splits=FOLDS).split(data.features, data.label, data.groups)):
        model = _fit(_model(), data.features[train], data.label[train])
        model_pred[test] = model.predict_proba(data.features[test])[:, 1]
        baseline = LogisticRegression(max_iter=1000).fit(_baseline_columns(data.features[train]), data.label[train])
        baseline_pred[test] = baseline.predict_proba(_baseline_columns(data.features[test]))[:, 1]
        fold_of[test] = fold
    return model_pred, baseline_pred, fold_of


def cross_fit_isotonic(pred: NDArray[np.float64], y: NDArray[np.int64], fold_of: NDArray[np.int64]) -> NDArray[np.float64]:
    calibrated = np.zeros(len(pred))
    for fold in np.unique(fold_of):
        train, test = fold_of != fold, fold_of == fold
        iso = IsotonicRegression(out_of_bounds="clip", y_min=0.0, y_max=1.0).fit(pred[train], y[train])
        calibrated[test] = iso.predict(pred[test])
    return calibrated


def leave_one_tournament_out(data: Dataset) -> dict[str, dict[str, float]]:
    results: dict[str, dict[str, float]] = {}
    for tournament in np.unique(data.tournaments):
        train, test = data.tournaments != tournament, data.tournaments == tournament
        model = _fit(_model(), data.features[train], data.label[train])
        baseline = LogisticRegression(max_iter=1000).fit(_baseline_columns(data.features[train]), data.label[train])
        results[str(int(tournament))] = {
            "states": int(test.sum()),
            "model_brier": _metrics(data.label[test], model.predict_proba(data.features[test])[:, 1])["brier"],
            "baseline_brier": _metrics(
                data.label[test], baseline.predict_proba(_baseline_columns(data.features[test]))[:, 1]
            )["brier"],
        }
    return results


@dataclass(frozen=True, slots=True)
class TrainingReport:
    run_id: int
    states: int
    chosen: str
    metrics: dict[str, dict[str, float]]
    holdout: dict[str, dict[str, float]]


def _write(conn: psycopg.Connection, data: Dataset, wp: NDArray[np.float64]) -> None:
    conn.execute("TRUNCATE analytics.round_wp_states, analytics.kill_impact")
    with conn.cursor() as cur:
        with cur.copy(
            """COPY analytics.round_wp_states (round_id, seq, event, kill_id, t_round_ms, attack_alive,
                   defense_alive, wp_attack) FROM STDIN"""
        ) as copy:
            for state, p in zip(data.states, wp, strict=True):
                copy.write_row((state.round_id, state.seq, state.event, state.kill_id, state.t_round_ms,
                                state.attack_alive, state.defense_alive, float(p)))
    conn.execute(
        """INSERT INTO analytics.kill_impact
           SELECT k.id, k.round_id, k.killer_id, k.victim_id, kr.side, vr.side, prev.wp_attack, cur.wp_attack,
                  CASE WHEN vr.side = 'attack' THEN cur.wp_attack - prev.wp_attack ELSE prev.wp_attack - cur.wp_attack END
           FROM analytics.round_wp_states cur
           JOIN analytics.round_wp_states prev ON prev.round_id = cur.round_id AND prev.seq = cur.seq - 1
           JOIN analytics.kills k ON k.id = cur.kill_id
           JOIN analytics.round_players vr ON vr.round_id = k.round_id AND vr.player_id = k.victim_id
           LEFT JOIN analytics.round_players kr ON kr.round_id = k.round_id AND kr.player_id = k.killer_id"""
    )


def train_win_probability(conn: psycopg.Connection) -> TrainingReport:
    data = build_dataset(conn)
    model_pred, baseline_pred, fold_of = out_of_fold(data)
    calibrated = cross_fit_isotonic(model_pred, data.label, fold_of)
    metrics = {
        "baseline_logistic": _metrics(data.label, baseline_pred),
        "lightgbm": _metrics(data.label, model_pred),
        "lightgbm_isotonic": _metrics(data.label, calibrated),
    }
    chosen = min(("lightgbm", "lightgbm_isotonic"), key=lambda name: metrics[name]["brier"])
    wp = calibrated if chosen == "lightgbm_isotonic" else model_pred
    holdout = leave_one_tournament_out(data)
    with conn.transaction():
        _write(conn, data, wp)
        row = conn.execute(
            """INSERT INTO analytics.model_runs (model, pipeline_version, seed, params, metrics)
               VALUES ('win_probability', %s, %s, %s, %s) RETURNING id""",
            (
                PIPELINE_VERSION,
                SEED,
                json.dumps({"lightgbm": PARAMS, "features": FEATURES, "folds": FOLDS, "chosen": chosen}),
                json.dumps({"out_of_fold": metrics, "leave_one_tournament_out": holdout, "states": len(data.label)}),
            ),
        ).fetchone()
    assert row is not None
    return TrainingReport(int(row[0]), len(data.label), chosen, metrics, holdout)
