"""Predict scoring, point-in-time adapters and full command integration."""

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from itertools import permutations
import json

import pytest

from f1fantasy import (
    account,
    cli,
    predict,
    predict_data as data,
    predict_model,
)
from f1fantasy import predict_account, predict_scheduler
from f1fantasy.data import DataError
from f1fantasy import web_predict


@pytest.fixture
def game():
    start = datetime(2099, 1, 2, tzinfo=timezone.utc)
    qs = [
        {
            "id": i + 1,
            "number": i + 1,
            "text": "Predict the podium" if i == 0 else "Who wins?",
            "subtext": "",
            "template": 1 if i == 0 else 3,
            "choice_limit": 3 if i == 0 else 1,
            "status": 2,
            "config": {},
            "options": [
                {
                    "id": str(j),
                    "name": str(j),
                    "points": (j * 5.0 if i == 0 else (5.0 if j == 1 else 30.0)),
                    "kind": 1,
                    "tla": str(j),
                    "team_id": "1",
                }
                for j in range(1, 5 if i == 0 else 3)
            ],
        }
        for i in range(10)
    ]
    return {
        "season": 2099,
        "scope": "round",
        "gameday_id": 1,
        "race_id": 10,
        "first_session_utc": start.isoformat(),
        "last_session_utc": (start + timedelta(days=1)).isoformat(),
        "fetched_at": (start - timedelta(days=1)).isoformat(),
        "deadline_utc": None,
        "deadline_authority": None,
        "locked": False,
        "questions": qs,
        "roster": [],
        "fixtures": [],
        "season_fixtures": [],
    }


def forecasts(game):
    return {
        q["id"]: (
            {
                "position_probabilities": {
                    "1": [0.5, 0.1, 0.1],
                    "2": [0.2, 0.4, 0.1],
                    "3": [0.1, 0.3, 0.3],
                    "4": [0.2, 0.2, 0.5],
                },
                "model_type": "podium",
            }
            if q["template"] == 1
            else {"probabilities": {"1": 0.7, "2": 0.3}, "model_type": "winner"}
        )
        for q in game["questions"]
    }


def test_expected_points_selects_payout_not_most_likely_answer(game):
    result = predict.select(game, forecasts(game))
    assert result["complete"]
    assert all(a["selected_options"] == ["2"] for a in result["answers"][1:])
    assert sum(a["booster_id"] == "1" for a in result["answers"]) == 1
    best = max(result["answers"], key=lambda a: a["expected_points_before_boost"])
    assert best["booster_id"] == "1"
    assert best["calibration"]["method"].startswith("uncalibrated")


def test_web_predict_publishes_cli_scoring_and_public_contract(monkeypatch, game):
    monkeypatch.setattr(data, "fetch", lambda season: game)
    monkeypatch.setattr(predict_model, "forecast", lambda *a, **k: forecasts(game))
    monkeypatch.setattr(predict, "pitstop_forecasts", lambda snapshot: {})
    publication = web_predict.build(2099)
    assert publication["status"] == "ready"
    assert publication["questions"] == game["questions"]
    recommendation = dict(publication["recommendation"])
    profiles = recommendation.pop("risk_profiles")
    assert recommendation == predict.select(game, forecasts(game))
    assert {name: result["risk_aversion"] for name, result in profiles.items()} == {
        "low": 0.5,
        "medium": 0.25,
        "high": 0.1,
    }
    assert all(
        "Joint podium outcomes" in result["unsupported"][0]["reason"]
        for result in profiles.values()
    )
    assert publication["question_fingerprint"] == data.fingerprint(game)
    assert publication["deadline_utc"] is None
    assert "roster" not in publication
    assert "fixtures" not in publication


def test_web_predict_locked_and_failed_feeds_do_not_publish_picks(monkeypatch, game):
    monkeypatch.setattr(data, "fetch", lambda season: game)
    monkeypatch.setattr(
        predict, "recommend", lambda *a, **k: pytest.fail("must not forecast")
    )
    game["locked"] = True
    assert web_predict.build(2099)["status"] == "locked"
    assert web_predict.build(2099)["recommendation"] is None
    game["locked"] = False
    game["first_session_utc"] = "2000-01-01T00:00:00Z"
    assert web_predict.build(2099)["status"] == "locked"

    def fail(season):
        raise DataError("Cannot verify questions")

    monkeypatch.setattr(data, "fetch", fail)
    publication = web_predict.build(2099)
    assert publication["status"] == "unavailable"
    assert "recommendation" not in publication
    assert publication["message"] == "Cannot verify questions"


def test_podium_assignment_matches_exhaustive_ordered_scores(game):
    result = predict.select(game, forecasts(game))["answers"][0]
    q, f = game["questions"][0], forecasts(game)[1]["position_probabilities"]

    def expected(ids):
        return sum(
            next(o["points"] for o in q["options"] if o["id"] == i)
            * (sum(f[i]) + f[i][slot])
            for slot, i in enumerate(ids)
        )

    assert result["expected_points_before_boost"] == pytest.approx(
        max(expected(ids) for ids in permutations(f, 3))
    )
    assert predict.score(q, ["1", "2", "3"], ["1", "3", "2"]) == 10 + 10 + 15
    assert predict.score(q, ["1", "2", "3"], ["1", "3", "2"], True) == 70


def test_podium_listed_payout_changes_optimal_boost_allocation(game):
    for question in game["questions"][1:]:
        question["options"][1]["points"] = 100
    result = predict.select(game, forecasts(game))
    podium = result["answers"][0]
    assert podium["selected_options"] == ["2", "3", "4"]
    assert podium["expected_points_before_boost"] == pytest.approx(52)
    assert podium["booster_id"] == "1"
    assert podium["expected_points"] == pytest.approx(104)
    assert all(answer["booster_id"] == "0" for answer in result["answers"][1:])
    assert result["expected_total_points"] == pytest.approx(374)


def test_podium_chance_can_outweigh_a_higher_exact_position_chance(game):
    for option in game["questions"][0]["options"]:
        option["points"] = 10
    probabilities = {
        "1": [0.30, 0.05, 0.05],
        "2": [0.25, 0.30, 0.30],
        "3": [0.05, 0.35, 0.05],
        "4": [0.05, 0.05, 0.35],
    }
    f = forecasts(game)
    f[1]["position_probabilities"] = probabilities
    # An exact-position-only optimizer would pick driver 1 for P1.
    exact = max(
        permutations(probabilities, 3),
        key=lambda ids: sum(probabilities[i][slot] for slot, i in enumerate(ids)),
    )
    assert exact == ("1", "3", "4")
    answer = predict.select(game, f)["answers"][0]
    assert answer["selected_options"] == ["2", "3", "4"]
    assert answer["expected_points_before_boost"] == pytest.approx(27)
    # All three still score even when every selected slot is wrong.
    assert (
        predict.score(game["questions"][0], answer["selected_options"], ["3", "4", "2"])
        == 30
    )


@pytest.mark.parametrize(
    "actual,points",
    [
        (["1", "2", "3"], 20),
        (["2", "1", "3"], 10),
        (["2", "3", "1"], 10),
        (["2", "3", "4"], 0),
    ],
)
@pytest.mark.parametrize("boosted", [False, True])
def test_podium_double_listed_or_zero_payout(game, actual, points, boosted):
    q = game["questions"][0]
    for option in q["options"]:
        option["points"] = 10 if option["id"] == "1" else 0
    multiplier = 2 if boosted else 1
    assert predict.score(q, ["1", "2", "3"], actual, boosted) == points * multiplier


@pytest.mark.parametrize("bad", [float("nan"), float("inf"), -0.01, 1.1])
def test_impossible_probabilities_fail(game, bad):
    f = forecasts(game)
    f[2]["probabilities"]["1"] = bad
    with pytest.raises(DataError, match="probabilities"):
        predict.select(game, f)


def test_unknown_semantics_never_become_complete_submission(game):
    f = forecasts(game)
    f[2] = {"unsupported": "unestablished predicate"}
    result = predict.select(game, f)
    assert not result["complete"] and len(result["answers"]) == 9
    assert result["unsupported"][0]["question_id"] == 2


@pytest.mark.parametrize(
    "change",
    ["duplicate", "podium_duplicate", "bad_boost", "two_boosts", "missing", "unknown"],
)
def test_answer_validation(game, change):
    answers = predict.select(game, forecasts(game))["answers"]
    if change == "duplicate":
        answers[1]["question_id"] = answers[0]["question_id"]
    if change == "podium_duplicate":
        answers[0]["selected_options"] = ["1", "1", "2"]
    if change == "bad_boost":
        answers[1]["booster_id"] = 1
    if change == "two_boosts":
        answers[1]["booster_id"] = answers[2]["booster_id"] = "1"
    if change == "missing":
        answers.pop()
    if change == "unknown":
        answers[1]["selected_options"] = ["999"]
    with pytest.raises(DataError):
        data.validate_answers(game, answers)


def test_fingerprint_tracks_points_but_not_result_status(game):
    expected = data.fingerprint(game)
    game["questions"][0]["status"] = 4
    assert data.fingerprint(game) == expected
    game["questions"][0]["options"][0]["points"] += 1
    assert data.fingerprint(game) != expected


def raw_questions():
    return [
        {
            "Id": i + 1,
            "No": i + 1,
            "Text": "Question",
            "SubText": "",
            "OptionTemplateId": 3,
            "Status": 2,
            "Config": {"ChoiceLimit": 1, "HiddenAnswer": "secret"},
            "Options": [
                {
                    "Id": 1,
                    "Value": "Yes",
                    "Points": "10",
                    "Type": 3,
                    "Position": "1",
                    "Chance": "90",
                },
                {
                    "Id": 2,
                    "Value": "No",
                    "Points": "20",
                    "Type": 3,
                    "Position": "0",
                    "Chance": "10",
                },
            ],
            "Answer": [{"Id": 1}],
        }
        for i in range(10)
    ]


def test_result_fields_and_public_hints_never_enter_model_inputs():
    qs = data.questions(raw_questions(), [])
    encoded = json.dumps(qs)
    for forbidden in ("Chance", "Position", "Answer", "HiddenAnswer"):
        assert forbidden not in encoded
    assert qs[0]["options"][0]["points"] == 10


def test_bonus_season_contradiction_fails_instead_of_silently_switching_year(
    monkeypatch,
):
    values = {
        "apps/web_config.json": {"currentSeasonYear": 2026},
        "limits/constraints.json": {
            "Data": {"Value": {"BonusRound": [{"BonusGamedayId": 25, "IsActive": 1}]}}
        },
        "schedule/raceday_en.json": {
            "Data": {
                "Value": [
                    {
                        "GamedayId": 25,
                        "Season": 2025,
                        "IsBonusRound": 1,
                        "IsPostponed": 0,
                    }
                ]
            }
        },
    }
    monkeypatch.setattr(data, "get", lambda path: values[path])
    with pytest.raises(DataError, match="contradictory"):
        data.fetch(2026, scope="season")


@pytest.mark.parametrize("season", [2027, 2030])
def test_future_season_accepts_the_same_verified_official_contract(monkeypatch, season):
    roster = [
        {
            "Id": i,
            "Value": f"Participant {i}",
            "Type": 1 if i <= 20 else 2,
            "IsActive": 1,
        }
        for i in range(1, 31)
    ]

    def envelope(value):
        return {"Data": {"Value": value}}

    values = {
        "apps/web_config.json": {"currentSeasonYear": season},
        "limits/constraints.json": envelope({"GamedayId": 1}),
        "schedule/raceday_en.json": envelope(
            [
                {
                    "GamedayId": 1,
                    "Season": season,
                    "IsBonusRound": 0,
                    "IsPostponed": 0,
                    "RaceDay": 1,
                    "MatchStatus": 1,
                    "RaceId": 10,
                    "SessionStartDateISO8601": f"{season}-03-01T12:00:00Z",
                    "SessionEndDateISO8601": f"{season}-03-01T14:00:00Z",
                }
            ]
        ),
        "drivers/drivers_1_en.json": envelope(roster),
        "questions/questions_1_en.json": envelope({"Questions": raw_questions()}),
    }
    monkeypatch.setattr(data, "get", lambda path: values[path])
    snapshot = data.fetch(season)
    assert snapshot["season"] == season
    assert len(snapshot["questions"]) == 10
    assert len(snapshot["roster"]) == 30
    assert not snapshot["locked"]

    values["questions/questions_1_en.json"]["Data"]["Value"]["Questions"][0][
        "OptionTemplateId"
    ] = 1
    with pytest.raises(DataError, match="podium contract"):
        data.fetch(season)
    values["apps/web_config.json"]["currentSeasonYear"] = season - 1
    with pytest.raises(DataError, match="official configuration"):
        data.fetch(season)


def save_archive(directory, snapshot, raw, *, actual=None, settled=None):
    row = {
        "version": 1,
        "snapshot": snapshot,
        "forecast": {str(k): v for k, v in raw.items()},
        "fingerprint": data.fingerprint(snapshot),
        "observed_at": snapshot["fetched_at"],
        "labels": actual,
        "settled_at": settled,
    }
    row["checksum"] = account._checksum(row)
    with account._locked(predict.archive_directory(directory)) as root:
        account._atomic(root / f"{snapshot['gameday_id']}.json", row)


def test_replay_uses_only_earlier_settled_prelock_archives(tmp_path, game):
    for day in range(1, 5):
        s = deepcopy(game)
        start = datetime(2026, 1, day * 3, tzinfo=timezone.utc)
        s.update(
            gameday_id=day,
            first_session_utc=start.isoformat(),
            last_session_utc=(start + timedelta(hours=2)).isoformat(),
            fetched_at=(start - timedelta(days=1)).isoformat(),
        )
        save_archive(
            tmp_path,
            s,
            forecasts(s),
            actual={
                str(q["id"]): (["1", "2", "3"] if q["template"] == 1 else ["1"])
                for q in s["questions"]
            },
            settled=(start + timedelta(days=1)).isoformat(),
        )
    result = predict.backtest(tmp_path)
    assert len(result["rounds"]) == 4 and result["question_count"] == 40
    assert result["rounds"][0]["questions"][1]["calibration"]["training_outcomes"] == 0
    assert result["rounds"][3]["questions"][1]["calibration"]["training_outcomes"] == 27
    assert (
        result["rounds"][3]["questions"][1]["calibration"]["method"]
        == "chronological_uniform_mixture"
    )
    assert all(
        "brier" in q and "log_loss" in q
        for r in result["rounds"]
        for q in r["questions"]
    )


def test_historical_current_feed_cannot_be_a_prelock_archive(tmp_path, game):
    game["fetched_at"] = game["first_session_utc"]
    save_archive(tmp_path, game, forecasts(game))
    with pytest.raises(DataError, match="point-in-time"):
        predict.backtest(tmp_path)


def test_recommend_archive_excludes_authenticated_identity(tmp_path, game, monkeypatch):
    game.update(
        answers=["private answer"], binding_fingerprint="private binding", guid="secret"
    )
    monkeypatch.setattr(predict_model, "forecast", lambda *a, **k: forecasts(game))
    monkeypatch.setattr(predict, "pitstop_forecasts", lambda *a: {})
    result = predict.recommend(game, directory=tmp_path)
    assert result["complete"]
    row = predict.archives(tmp_path)[0]
    assert not {"answers", "binding_fingerprint", "guid"} & row["snapshot"].keys()


def test_official_stationary_pitstop_labels_have_publication_cutoff(game, monkeypatch):
    class Clock(datetime):
        @classmethod
        def now(cls, tz=None):
            return cls(2099, 1, 2, tzinfo=timezone.utc)

    monkeypatch.setattr(predict, "datetime", Clock)
    game["questions"][1]["text"] = "Which team will set the fastest pitstop time?"
    game["season_fixtures"] = [
        {
            "SessionEndDateISO8601": "2026-01-01T00:00:00Z",
            "MatchStatus": 4,
            "GamedayId": i,
        }
        for i in (1, 2)
    ]

    def feed(path):
        return {
            "Meta": {
                "Timestamp": {
                    "UTCTime": "01/01/2099 12:00:00 AM"
                    if "_1_" in path
                    else "01/03/2099 12:00:00 AM"
                }
            },
            "Data": {
                "Value": {
                    "Questions": [
                        {
                            "Text": "fastest pitstop",
                            "Status": 4,
                            "Answer": [{"Id": "1", "Type": 2}],
                        }
                    ]
                }
            },
        }

    monkeypatch.setattr(data, "get", feed)
    f = predict.pitstop_forecasts(game)[2]
    assert f["evidence"]["gamedays"] == [1]
    assert f["probabilities"] == {"1": pytest.approx(2 / 3), "2": pytest.approx(1 / 3)}


def test_cli_public_questions_and_partial_recommendations(
    game, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(data, "fetch", lambda *a: game)
    assert cli.main(["predict", "questions", "--format", "json"]) == 0
    assert len(json.loads(capsys.readouterr().out)["data"]["questions"]) == 10
    raw = forecasts(game)
    raw[2] = {"unsupported": "unknown semantics"}
    monkeypatch.setattr(predict_model, "forecast", lambda *a, **k: raw)
    monkeypatch.setattr(predict, "pitstop_forecasts", lambda *a: {})
    assert (
        cli.main(
            ["--account-dir", str(tmp_path), "predict", "recommend", "--format", "json"]
        )
        == 1
    )
    assert json.loads(capsys.readouterr().out)["status"] == "partial"


def test_cli_pending_recovery_precedes_new_model(game, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr(
        predict_account, "recover", lambda *a: {"apply_status": "verified"}
    )
    monkeypatch.setattr(
        predict_account, "show", lambda *a: pytest.fail("must not replan pending work")
    )
    assert (
        cli.main(
            [
                "--account-dir",
                str(tmp_path),
                "predict",
                "account",
                "apply",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert json.loads(capsys.readouterr().out)["data"]["apply_status"] == "verified"


def test_cli_apply_with_no_pending_journal_actually_generates_and_applies(
    game, monkeypatch, tmp_path, capsys
):
    monkeypatch.setattr(
        predict_account,
        "recover",
        lambda *a: {**game, "apply_status": "nothing_to_recover"},
    )
    monkeypatch.setattr(predict_model, "forecast", lambda *a, **k: forecasts(game))
    monkeypatch.setattr(predict, "pitstop_forecasts", lambda *a: {})
    calls = []

    def apply(directory, season, proposal):
        calls.append(proposal)
        assert proposal["complete"] and len(proposal["answers"]) == 10
        return {"apply_status": "verified"}

    monkeypatch.setattr(predict_account, "apply", apply)
    assert (
        cli.main(
            [
                "--account-dir",
                str(tmp_path),
                "predict",
                "account",
                "apply",
                "--format",
                "json",
            ]
        )
        == 0
    )
    assert len(calls) == 1
    assert json.loads(capsys.readouterr().out)["data"]["apply_status"] == "verified"


def test_repeated_same_round_archives_do_not_manufacture_calibration_samples(game):
    row = {
        "snapshot": game,
        "forecast": forecasts(game),
        "observed_at": "2026-01-01T00:00:00Z",
        "settled_at": "2026-01-05T00:00:00Z",
        "labels": {
            str(q["id"]): ["1", "2", "3"] if q["template"] == 1 else ["1"]
            for q in game["questions"]
        },
    }
    result = predict.select(game, forecasts(game), [row] * 30)
    assert result["answers"][1]["calibration"]["training_outcomes"] == 9
    assert result["answers"][1]["calibration"]["method"].startswith("uncalibrated")


def test_predict_daemon_once_headless_and_restores_environment(
    monkeypatch, tmp_path, capsys
):
    monkeypatch.delenv("F1FANTASY_HEADLESS", raising=False)
    monkeypatch.setattr(predict, "settle", lambda *a: {})

    def tick(*a, **kw):
        import os

        assert os.environ["F1FANTASY_HEADLESS"] == "1"
        return {"status": "blocked", "reason": "no exact official deadline"}

    monkeypatch.setattr(predict_scheduler, "tick", tick)
    assert (
        cli.main(
            [
                "--account-dir",
                str(tmp_path),
                "predict",
                "daemon",
                "run",
                "--once",
                "--format",
                "json",
            ]
        )
        == 1
    )
    assert "blocked" in capsys.readouterr().out
    import os

    assert "F1FANTASY_HEADLESS" not in os.environ
