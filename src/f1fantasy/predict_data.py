"""Fresh official Predict contracts, isolated from Fantasy prices and scoring."""

from __future__ import annotations

from datetime import datetime, timezone
import hashlib
import json
import math
import re
import time

import requests

from .data import DataError

BASE = "https://f1predict.formula1.com"
REVIEWED_RULES_SEASON = 2026


def utc(value):
    try:
        result = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except ValueError:
        raise DataError("Predict timestamp must include a timezone") from None


def get(path):
    try:
        response = requests.get(
            BASE + "/feeds/" + path,
            params={"buster": time.time_ns()},
            headers={"Cache-Control": "no-cache"},
            timeout=25,
            allow_redirects=False,
        )
        response.raise_for_status()
        body = response.json()
        if (
            not isinstance(body, dict)
            or body.get("Meta", {}).get("Success", True) is not True
        ):
            raise ValueError
        return body
    except (requests.RequestException, ValueError):
        raise DataError("Cannot verify fresh official Predict feed: " + path) from None


def value(body):
    try:
        return body["Data"]["Value"]
    except (KeyError, TypeError):
        raise DataError("Unrecognized official Predict feed envelope") from None


def integer(value_, minimum=0):
    if (
        isinstance(value_, bool)
        or not isinstance(value_, (str, int))
        or not re.fullmatch(r"\d+", str(value_))
        or int(value_) < minimum
    ):
        raise DataError("Invalid Predict integer identity/configuration")
    return int(value_)


def roster(rows):
    result = []
    for row in rows:
        if integer(row["IsActive"]) != 1:
            continue
        kind = integer(row["Type"], 1)
        if kind not in (1, 2):
            raise DataError("Unknown Predict roster kind")
        result.append(
            {
                "id": str(integer(row["Id"], 1)),
                "name": str(row["Value"]),
                "kind": kind,
                "tla": str(row.get("DriverTLA", "")),
                "team_id": str(row.get("TeamId", row["Id"])),
                "team_name": str(row.get("TeamName", row["Value"])),
            }
        )
    if (
        len({r["id"] for r in result}) != len(result)
        or sum(r["kind"] == 1 for r in result) < 20
        or sum(r["kind"] == 2 for r in result) < 10
    ):
        raise DataError("Predict active roster is incomplete or duplicated")
    return result


def questions(rows, players):
    """Allowlist features: official Answer, Position and Chance never escape."""
    catalog = {p["id"]: p for p in players}
    result = []
    for row in rows:
        options = []
        for raw in row["Options"]:
            ident, kind = str(integer(raw["Id"], 1)), integer(raw["Type"], 1)
            points = float(raw["Points"])
            if kind not in (1, 2, 3) or not math.isfinite(points) or points < 0:
                raise DataError("Unverified Predict option points/type")
            player = catalog.get(ident, {}) if kind != 3 else {}
            if kind != 3 and player.get("kind") != kind:
                raise DataError("Predict option is absent from its own active roster")
            options.append(
                {
                    "id": ident,
                    "name": str(raw["Value"]),
                    "points": points,
                    "kind": kind,
                    "tla": player.get("tla", ""),
                    "team_id": player.get("team_id", ""),
                }
            )
        count = integer(row["Config"]["ChoiceLimit"], 1)
        template = integer(row["OptionTemplateId"], 1)
        if count > len(options) or len({o["id"] for o in options}) != len(options):
            raise DataError("Invalid Predict legal answer set")
        if template == 1 and (count != 3 or any(o["kind"] != 1 for o in options)):
            raise DataError("Unknown ordered Predict podium contract")
        result.append(
            {
                "id": integer(row["Id"], 1),
                "number": integer(row["No"], 1),
                "text": str(row["Text"]),
                "subtext": str(row.get("SubText", "")),
                "template": template,
                "choice_limit": count,
                "status": integer(row["Status"]),
                "config": {
                    k: row["Config"][k]
                    for k in (
                        "ChoiceLimit",
                        "Driver",
                        "Constructor",
                        "MinValue",
                        "MaxValue",
                        "StepValue",
                        "IsMinValueExtended",
                        "IsMaxValueExtended",
                    )
                    if k in row["Config"]
                },
                "options": options,
            }
        )
    if (
        len(result) != 10
        or len({q["id"] for q in result}) != 10
        or {q["number"] for q in result} != set(range(1, 11))
    ):
        raise DataError("Official Predict round must have ten distinct questions")
    return sorted(result, key=lambda q: q["number"])


def fetch(season, gameday_id=None, scope="round"):
    if season != REVIEWED_RULES_SEASON:
        raise DataError(
            "Predict scoring rules require an official rules/FAQ review for this season"
        )
    try:
        config = get("apps/web_config.json")
        if integer(config["currentSeasonYear"]) != season or scope not in {
            "round",
            "season",
        }:
            raise DataError("Predict season/scope differs from official configuration")
        constraints = value(get("limits/constraints.json"))
        fixtures = value(get("schedule/raceday_en.json"))
        if gameday_id is None:
            if scope == "round":
                gameday_id = integer(constraints["GamedayId"], 1)
            else:
                ids = [
                    integer(b["BonusGamedayId"], 1)
                    for b in constraints["BonusRound"]
                    if integer(b["IsActive"]) == 1
                ]
                if len(ids) != 1:
                    raise DataError("No unique explicit Predict season bonus")
                gameday_id = ids[0]
        chosen = [r for r in fixtures if integer(r["GamedayId"]) == gameday_id]
        if not chosen or any(
            integer(r["Season"]) != season
            or bool(integer(r["IsBonusRound"])) != (scope == "season")
            or integer(r["IsPostponed"])
            for r in chosen
        ):
            raise DataError(
                "Predict event/bonus season metadata is contradictory or postponed"
            )
        chosen.sort(key=lambda r: integer(r["RaceDay"]))
        statuses = [integer(r["MatchStatus"]) for r in chosen]
        if any(s not in range(7) for s in statuses):
            raise DataError("Unknown official Predict round status")
        players = roster(value(get(f"drivers/drivers_{gameday_id}_en.json")))
        qs = questions(
            value(get(f"questions/questions_{gameday_id}_en.json"))["Questions"],
            players,
        )
        return {
            "season": season,
            "scope": scope,
            "gameday_id": gameday_id,
            "race_id": integer(chosen[0]["RaceId"], 1),
            "fixtures": chosen,
            "season_fixtures": [
                r
                for r in fixtures
                if integer(r["Season"]) == season and not integer(r["IsBonusRound"])
            ],
            "first_session_utc": min(
                utc(r["SessionStartDateISO8601"]) for r in chosen
            ).isoformat(),
            "last_session_utc": max(
                utc(r["SessionEndDateISO8601"]) for r in chosen
            ).isoformat(),
            "deadline_utc": None,
            "deadline_authority": None,
            "locked": any(s not in (0, 1) for s in statuses)
            or any(q["status"] not in (1, 2) for q in qs),
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "questions": qs,
            "roster": players,
        }
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, DataError):
            raise
        raise DataError(
            "Cannot verify official Predict questions/schedule/options"
        ) from None


def fingerprint(snapshot):
    # Question status changes after lock; it is checked independently from the
    # immutable question/answer/points identity used for settlement and recovery.
    frame = {
        k: snapshot[k]
        for k in ("season", "scope", "gameday_id", "race_id", "first_session_utc")
    }
    frame["questions"] = [
        {k: v for k, v in q.items() if k != "status"} for q in snapshot["questions"]
    ]
    return hashlib.sha256(
        json.dumps(frame, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def validate_answers(snapshot, answers):
    if not isinstance(answers, list) or len(answers) != len(snapshot["questions"]):
        raise DataError("Predict submission requires every question")
    catalog = {q["id"]: q for q in snapshot["questions"]}
    seen, boosts = set(), 0
    for row in answers:
        try:
            q = catalog[row["question_id"]]
            ids, boost = row["selected_options"], row["booster_id"]
            if (
                row["question_id"] in seen
                or not isinstance(ids, list)
                or len(ids) != q["choice_limit"]
                or any(not isinstance(i, str) for i in ids)
                or len(set(ids)) != len(ids)
                or not set(ids) <= {o["id"] for o in q["options"]}
                or boost not in ("0", "1")
            ):
                raise ValueError
            seen.add(q["id"])
            boosts += boost == "1"
        except (KeyError, TypeError, ValueError):
            raise DataError(
                "Illegal Predict question/cardinality/ordered answers"
            ) from None
    if boosts > 1:
        raise DataError("Predict permits only one boosted question")


def labels(snapshot):
    """Fetch settlement separately; never feed returned outcomes to a forecast."""
    body = get(f"questions/questions_{snapshot['gameday_id']}_en.json")
    raw = value(body)["Questions"]
    if questions(raw, snapshot["roster"]) != [
        dict(q, status=4) for q in snapshot["questions"]
    ] or any(integer(q["Status"]) != 4 for q in raw):
        raise DataError(
            "Predict answers not finalized or original question/options/points changed"
        )
    output = {}
    for row in raw:
        question = next(
            q for q in snapshot["questions"] if q["id"] == integer(row["Id"], 1)
        )
        allowed = {o["id"] for o in question["options"]}
        if question["template"] == 1 and {
            integer(a["Position"]) for a in row["Answer"]
        } != {1, 2, 3}:
            raise DataError("Official Predict podium result order cannot be verified")
        ordered = sorted(row["Answer"], key=lambda a: integer(a["Position"]))
        ids = [str(integer(a["Id"], 1)) for a in ordered]
        if (
            len(set(ids)) != len(ids)
            or not set(ids) <= allowed
            or len(ids) > question["choice_limit"]
        ):
            raise DataError("Unverified official Predict result labels")
        output[str(row["Id"])] = ids
    return output
