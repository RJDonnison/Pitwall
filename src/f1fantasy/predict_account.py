"""Cookie-backed Predict account access and reconciled single-question writes.

Private contracts are those shipped by the official Predict client, not a public
API. An explicit event-bound remote lock timestamp is required to send answers.
All state lives below ``directory/predict``; Fantasy profiles are never opened.
"""

from __future__ import annotations

from contextlib import contextmanager
from contextvars import ContextVar
from copy import deepcopy
from datetime import datetime, timezone
import hashlib
import importlib
import json
import os
from pathlib import Path
import re
import shutil
import time
from urllib.parse import urlsplit

from . import account as security

BASE = "https://f1predict.formula1.com"
SAVE = "/services/user/gameplay/prediction"
READ = re.compile(r"^/services/user/gameplay/([A-Za-z0-9_-]+)/(\d+)/prediction$")
HEADERS = {
    "entity": "d3@t4N0te!",
    "Accept": "application/json",
    "Content-Type": "application/json",
    "Cache-Control": "no-cache",
}
AUTHORITY = "official-markup:prediction-lock"
_CUTOFF = ContextVar("predict_safety_cutoff", default=None)
_EXPECTED = ContextVar("predict_scheduled_precondition", default=None)


@contextmanager
def _safety_cutoff(cutoff, *, expected=None):
    """Scheduler may shorten, never extend, the official submission window."""
    token = _CUTOFF.set(cutoff)
    expected_token = _EXPECTED.set(
        _precondition(expected) if expected is not None else None
    )
    try:
        yield
    finally:
        _EXPECTED.reset(expected_token)
        _CUTOFF.reset(token)


class PredictAccountError(security.AccountError):
    """Predict evidence is missing, expired, conflicting, or unsafe to replay."""


AccountError = PredictAccountError


def storage_directory(path: Path) -> Path:
    return Path(path) / "predict"


def _now():
    return datetime.now(timezone.utc)


def _timestamp(value):
    try:
        if not isinstance(value, str):
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except ValueError:
        raise AccountError(
            "Predict requires an explicit timezone-bearing timestamp"
        ) from None


def _positive(value, label):
    if type(value) is not int or value < 1:
        raise AccountError(f"Invalid Predict {label}")
    return value


def _digest(value):
    return hashlib.sha256(
        json.dumps(value, sort_keys=True, allow_nan=False).encode()
    ).hexdigest()


def _api():
    # The public-data module owns question/option/points validation.
    return importlib.import_module(".predict_data", __package__)


def _fetch(season, gameday_id=None, scope="round"):
    _positive(season, "season")
    if gameday_id is not None:
        _positive(gameday_id, "gameday")
    if scope not in {"round", "season"}:
        raise AccountError("Predict scope must explicitly be round or season")
    value = _api().fetch(season, gameday_id=gameday_id, scope=scope)
    try:
        if (
            value["season"] != season
            or type(value["season"]) is not int
            or value["scope"] != scope
            or (gameday_id is not None and value["gameday_id"] != gameday_id)
            or type(value["locked"]) is not bool
        ):
            raise ValueError
        _positive(value["gameday_id"], "gameday")
        _positive(value["race_id"], "race")
        _timestamp(value["first_session_utc"])
        _timestamp(value["fetched_at"])
        questions = value["questions"]
        if len(questions) != 10 or len({q["id"] for q in questions}) != 10:
            raise ValueError
        for q in questions:
            _positive(q["id"], "question")
            _positive(q["choice_limit"], "cardinality")
            if q["template"] not in {1, 2, 3, 4, 6, 7, 8}:
                raise ValueError
        _api().fingerprint(value)
    except (KeyError, TypeError, ValueError):
        raise AccountError(
            "Public Predict identity/questions cannot be verified"
        ) from None
    return value


def _unwrap(body):
    if not isinstance(body, dict) or not isinstance(body.get("Meta"), dict):
        raise AccountError("Unrecognized Predict response envelope")
    if body["Meta"].get("Success") is not True:
        raise AccountError("Predict authentication expired or request rejected")
    if not isinstance(body.get("Data"), dict) or "Value" not in body["Data"]:
        raise AccountError("Unrecognized Predict response value")
    return body["Data"]["Value"]


class _Session:
    def __init__(self, context):
        self.context = context
        self.page = context.new_page()
        self.observations = []
        self.failed = False
        context.route("**/services/**", self._route)
        self.page.on("response", self._observe)

    @staticmethod
    def _route(route):
        request = route.request
        url = urlsplit(request.url)
        # SSO bridging is authentication, not answer/profile/terms acceptance.
        login = (
            f"{url.scheme}://{url.netloc}" == BASE
            and url.path == "/services/session/login"
        )
        if request.method in {"GET", "HEAD"} or (request.method == "POST" and login):
            route.continue_()
        else:
            route.abort()

    def _observe(self, response):
        url = urlsplit(response.url)
        match = (
            READ.fullmatch(url.path) if f"{url.scheme}://{url.netloc}" == BASE else None
        )
        if not match:
            return
        try:
            if response.status != 200:
                raise ValueError
            value = _unwrap(response.json())
            if not isinstance(value, dict) or not isinstance(
                value.get("Predictions"), list
            ):
                raise ValueError
            self.observations.append({"guid": match[1], "gameday_id": int(match[2])})
        except Exception:
            self.failed = True

    def observe(self, gameday_id, timeout_seconds=30, *, manual=False):
        self.observations.clear()
        self.failed = False
        try:
            self.page.goto(
                f"{BASE}/en/gameplay/{gameday_id}", wait_until="domcontentloaded"
            )
            end = time.monotonic() + timeout_seconds
            while time.monotonic() < end:
                if self.failed and not manual:
                    raise AccountError(
                        "Predict authentication expired; reconnect manually"
                    )
                if len({r["guid"] for r in self.observations}) > 1:
                    raise AccountError(
                        "Conflicting official Predict account identities"
                    )
                matching = [
                    r for r in self.observations if r["gameday_id"] == gameday_id
                ]
                if matching:
                    return matching[-1]
                self.page.wait_for_timeout(200)
        except AccountError:
            raise
        except Exception:
            raise AccountError(
                "Official Predict browser unavailable; reconnect manually"
            ) from None
        raise AccountError(
            "No authenticated official prediction read observed; complete login/MFA"
        )

    def get(self, path):
        try:
            response = self.context.request.get(
                BASE + path,
                params={"buster": time.time_ns()},
                headers=HEADERS,
                timeout=20000,
                max_redirects=0,
                max_retries=0,
            )
            if response.status != 200:
                raise ValueError
            return _unwrap(response.json())
        except Exception:
            raise AccountError(
                "Fresh Predict read unavailable or authentication expired"
            ) from None

    def post(self, payload):
        try:
            response = self.context.request.post(
                BASE + SAVE,
                data=payload,
                headers=HEADERS,
                timeout=20000,
                max_redirects=0,
                max_retries=0,
            )
            if response.status != 200:
                raise ValueError
            _unwrap(response.json())
        except Exception:
            raise AccountError(
                "Predict save outcome unknown; reconcile before any retry"
            ) from None

    def deadline(self, snapshot):
        if self.page.url != f"{BASE}/en/gameplay/{snapshot['gameday_id']}":
            return None
        # No such explicit markup was found in research. Countdowns, session
        # starts, config dates, and caller-supplied flags never qualify here.
        selector = (
            '[aria-label="prediction lock deadline"]'
            f'[data-gameday-id="{snapshot["gameday_id"]}"]'
            f'[data-race-id="{snapshot["race_id"]}"] time[datetime]'
        )
        values = self.page.locator(selector).evaluate_all(
            "es => es.map(e => e.getAttribute('datetime'))"
        )
        if not values:
            return None
        dates = {_timestamp(v).isoformat() for v in values}
        if len(dates) != 1:
            raise AccountError("Conflicting official Predict lock timestamps")
        return dates.pop()


@contextmanager
def _browser(root):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise AccountError(
            "Install the optional account dependency for Playwright"
        ) from None
    profile = root / "browser"
    security._private_directory(profile)
    executable = (
        os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
        or shutil.which("chromium")
        or shutil.which("chromium-browser")
    )
    options = {
        "headless": os.environ.get("F1PREDICT_HEADLESS") == "1",
        "service_workers": "block",
    }
    if executable:
        options["executable_path"] = executable
    with sync_playwright() as p:
        try:
            context = p.chromium.launch_persistent_context(str(profile), **options)
        except Exception:
            raise AccountError(
                "Cannot open dedicated Predict browser; check Chromium/display/profile lock"
            ) from None
        try:
            yield _Session(context)
        finally:
            context.close()


def _binding(root, season):
    path = root / "binding.json"
    if not path.exists():
        raise AccountError("Predict is not connected")
    value = security._read_json(path)
    if (
        not isinstance(value, dict)
        or value.get("service") != "predict"
        or value.get("season") != season
        or not isinstance(value.get("guid"), str)
        or not re.fullmatch(r"[A-Za-z0-9_-]+", value["guid"])
    ):
        raise AccountError(
            "Predict binding identity/season invalid; reconnect explicitly"
        )
    return value


def binding_fingerprint(binding):
    return _digest({k: binding[k] for k in ("service", "season", "guid")})


def _answers(value, snapshot, guid):
    if not isinstance(value, dict) or not isinstance(value.get("Predictions"), list):
        raise AccountError("Unrecognized authenticated Predict answer list")
    for key, expected in (
        ("GUID", guid),
        ("GameDayId", snapshot["gameday_id"]),
        ("RaceId", snapshot["race_id"]),
    ):
        if key in value and value[key] != expected:
            raise AccountError(
                "Predict response identity conflicts with bound event/account"
            )
    questions = {q["id"]: q for q in snapshot["questions"]}
    rows = {}
    for raw in value["Predictions"]:
        try:
            qid = _positive(raw["QuestionId"], "question ID")
            question = questions[qid]
            selected = raw["SelectedOption"]
            boost = raw["BoosterId"]
            if (
                not isinstance(selected, list)
                or boost not in ("0", "1")
                or not isinstance(boost, str)
            ):
                raise ValueError
            if any(
                isinstance(v, bool) or not isinstance(v, (str, int)) for v in selected
            ):
                raise ValueError
            selected = [str(v) for v in selected]
            nonempty = [v for v in selected if v != "0"]
            allowed = {o["id"] for o in question["options"]}
            if (
                qid in rows
                or len(selected) > question["choice_limit"]
                or len(set(nonempty)) != len(nonempty)
                or not set(nonempty) <= allowed
                or ("0" in selected and question["template"] not in (1, 2))
                or (boost == "1" and not nonempty)
            ):
                raise ValueError
            rows[qid] = {
                "question_id": qid,
                "selected_options": selected,
                "booster_id": boost,
            }
        except (KeyError, TypeError, ValueError):
            raise AccountError(
                "Malformed, duplicate, or unknown official Predict selections"
            ) from None
    result = [
        rows.get(
            q["id"], {"question_id": q["id"], "selected_options": [], "booster_id": "0"}
        )
        for q in sorted(questions.values(), key=lambda q: q["number"])
    ]
    if sum(r["booster_id"] == "1" for r in result) > 1:
        raise AccountError("Conflicting official Predict chip allocation")
    return result


def _snapshot(session, binding, gameday_id=None, scope="round", *, observed=None):
    public = _fetch(binding["season"], gameday_id, scope)
    observed = observed or session.observe(public["gameday_id"])
    if (
        observed["guid"] != binding["guid"]
        or observed["gameday_id"] != public["gameday_id"]
    ):
        raise AccountError("Observed Predict account/event differs from binding")
    # Manual login may have taken minutes; obtain another public snapshot now.
    public = deepcopy(_fetch(binding["season"], public["gameday_id"], scope))
    answers = _answers(
        session.get(
            f"/services/user/gameplay/{binding['guid']}/{public['gameday_id']}/prediction"
        ),
        public,
        binding["guid"],
    )
    public["deadline_utc"] = session.deadline(public)
    public["deadline_authority"] = AUTHORITY if public["deadline_utc"] else None
    public.update(
        answers=answers,
        binding_fingerprint=binding_fingerprint(binding),
        question_fingerprint=_api().fingerprint(public),
    )
    return public


def _journal(root):
    path = root / "journal.json"
    rows = security._read_json(path) if path.exists() else []
    try:
        if not isinstance(rows, list):
            raise ValueError
        for row in rows:
            if row["checksum"] != security._checksum(row) or row["status"] not in {
                "ready",
                "prepared",
                "unknown",
                "verified",
            }:
                raise ValueError
            if not isinstance(row["steps"], list):
                raise ValueError
            for step in row["steps"]:
                if (
                    step["status"] not in {"ready", "prepared", "unknown", "verified"}
                    or not isinstance(step["expected"], list)
                    or not isinstance(step["before"], list)
                ):
                    raise ValueError
    except (KeyError, TypeError, ValueError):
        raise AccountError("Invalid Predict journal integrity; no replay") from None
    return rows


def _save(root, rows):
    for row in rows:
        row["checksum"] = security._checksum(row)
    security._atomic(root / "journal.json", rows)


def _recommendation(value, snapshot):
    try:
        if not isinstance(value, dict) or value.get("complete") is not True:
            raise ValueError
        for key in ("season", "gameday_id", "race_id", "scope", "question_fingerprint"):
            if (
                type(value[key]) is not type(snapshot[key])
                or value[key] != snapshot[key]
            ):
                raise ValueError
        _api().validate_answers(snapshot, value["answers"])
        answers = [
            {k: r[k] for k in ("question_id", "selected_options", "booster_id")}
            for r in value["answers"]
        ]
        # Validate IDs/order/chip even if an independently provided validator is lax.
        parsed = _answers(
            {
                "Predictions": [
                    {
                        "QuestionId": r["question_id"],
                        "SelectedOption": r["selected_options"],
                        "BoosterId": r["booster_id"],
                    }
                    for r in answers
                ]
            },
            snapshot,
            "",
        )
        if len(answers) != 10 or any(
            len(r["selected_options"])
            != next(
                q["choice_limit"]
                for q in snapshot["questions"]
                if q["id"] == r["question_id"]
            )
            or "0" in r["selected_options"]
            for r in parsed
        ):
            raise ValueError
        return {
            **{
                k: value[k]
                for k in (
                    "season",
                    "gameday_id",
                    "race_id",
                    "scope",
                    "question_fingerprint",
                )
            },
            "complete": True,
            "answers": parsed,
        }
    except (KeyError, TypeError, ValueError):
        raise AccountError(
            "Predict recommendation incomplete or stale; recompute from fresh questions/points"
        ) from None


def _frame(snapshot):
    return {
        k: snapshot[k]
        for k in (
            "season",
            "gameday_id",
            "race_id",
            "scope",
            "question_fingerprint",
            "deadline_utc",
            "deadline_authority",
            "first_session_utc",
        )
    }


def _precondition(snapshot):
    return _digest(
        {
            "frame": _frame(snapshot),
            "answers": snapshot["answers"],
            "binding": snapshot["binding_fingerprint"],
        }
    )


def _writable(snapshot):
    if snapshot["locked"]:
        raise AccountError("Predict round is locked")
    if snapshot.get("deadline_authority") != AUTHORITY or not snapshot.get(
        "deadline_utc"
    ):
        raise AccountError(
            "Predict writes blocked: no authoritative exact remote deadline"
        )
    if _now() >= _timestamp(snapshot["deadline_utc"]):
        raise AccountError("Predict deadline has passed")
    if _CUTOFF.get() is not None and _now() >= _CUTOFF.get():
        raise AccountError("Predict scheduler safety cutoff reached")


def _steps(snapshot, target):
    current = deepcopy(snapshot["answers"])
    wanted = {r["question_id"]: r for r in target}
    order = [r["question_id"] for r in current]
    # Explicitly clear/move the old chip before installing another; each step
    # then has an unambiguous full-account expected postcondition.
    old = next((r["question_id"] for r in current if r["booster_id"] == "1"), None)
    if old is not None and wanted[old]["booster_id"] == "0":
        order.remove(old)
        order.insert(0, old)
    steps = []
    for qid in order:
        index = next(i for i, r in enumerate(current) if r["question_id"] == qid)
        if current[index] == wanted[qid]:
            continue
        before = deepcopy(current)
        current[index] = deepcopy(wanted[qid])
        answer = wanted[qid]
        steps.append(
            {
                "status": "ready",
                "before": before,
                "expected": deepcopy(current),
                "payload": {
                    "RaceId": snapshot["race_id"],
                    "GameDayId": snapshot["gameday_id"],
                    "PlatformId": 1,
                    "Predictions": [
                        {
                            "QuestionId": qid,
                            "SelectedOption": answer["selected_options"],
                            "BoosterId": answer["booster_id"],
                        }
                    ],
                },
            }
        )
    return steps


def _run(root, rows, row, session, binding, live):
    if row["binding"] != binding_fingerprint(binding):
        raise AccountError("Predict journal belongs to a different account")
    if any(
        live[k] != row["frame"][k]
        for k in ("season", "gameday_id", "race_id", "scope", "question_fingerprint")
    ):
        raise AccountError(
            "Predict journal event/questions/points differ from fresh readback"
        )
    for step in row["steps"]:
        if step["status"] == "verified":
            continue
        if step["status"] in {"prepared", "unknown"}:
            # A response/timeout/process crash can never authorize resending.
            if live["answers"] != step["expected"]:
                step["status"] = row["status"] = "unknown"
                _save(root, rows)
                raise AccountError("Predict outcome unresolved; no blind resend")
            step["status"] = "verified"
            _save(root, rows)
            continue
        if live["answers"] != step["before"]:
            raise AccountError(
                "Predict answers changed outside this journal; no overwrite"
            )
        if _frame(live) != row["frame"]:
            raise AccountError(
                "Predict questions/points/event/window changed; recompute before ready steps"
            )
        _recommendation(row["recommendation"], live)
        _writable(live)
        step["status"] = row["status"] = "prepared"
        step["prepared_at"] = _now().isoformat()
        _save(root, rows)
        # Durable preparation precedes any network mutation. A local deadline
        # check again prevents a disk stall from overrunning the verified cutoff.
        _writable(live)
        try:
            session.post(step["payload"])
        except Exception:
            pass  # Even a rejected/unknown response requires official readback.
        try:
            live = _snapshot(
                session, binding, row["frame"]["gameday_id"], row["frame"]["scope"]
            )
        except Exception:
            step["status"] = row["status"] = "unknown"
            _save(root, rows)
            raise AccountError(
                "Predict post-write readback unavailable; no replay"
            ) from None
        if live["answers"] != step["expected"] or any(
            live[k] != row["frame"][k]
            for k in (
                "season",
                "gameday_id",
                "race_id",
                "scope",
                "question_fingerprint",
            )
        ):
            step["status"] = row["status"] = "unknown"
            _save(root, rows)
            raise AccountError(
                "Predict readback mismatch, including unaffected answers/chip; no replay"
            )
        step["status"] = "verified"
        _save(root, rows)
    if live["answers"] != row["expected"]:
        raise AccountError(
            "Verified Predict answers changed; original proposal will not overwrite them"
        )
    row["status"] = "verified"
    row["verified_at"] = _now().isoformat()
    _save(root, rows)
    return {**live, "apply_status": "verified", "journal_key": row["key"]}


def connect(directory: Path, season: int, timeout_seconds: int = 300) -> dict:
    _positive(timeout_seconds, "login timeout")
    with (
        security._locked(storage_directory(directory)) as root,
        _browser(root) as session,
    ):
        public = _fetch(season)
        observed = session.observe(public["gameday_id"], timeout_seconds, manual=True)
        binding = {"service": "predict", "season": season, "guid": observed["guid"]}
        if (
            (root / "binding.json").exists()
            and _binding(root, season) != binding
            and _journal(root)
        ):
            raise AccountError(
                "Predict journal already bound to another identity; use another directory"
            )
        live = _snapshot(session, binding, public["gameday_id"], observed=observed)
        security._atomic(root / "binding.json", binding)
        return live


def show(
    directory: Path, season: int, gameday_id: int | None = None, scope: str = "round"
) -> dict:
    with (
        security._locked(storage_directory(directory)) as root,
        _browser(root) as session,
    ):
        return _snapshot(session, _binding(root, season), gameday_id, scope)


def apply(directory: Path, season: int, recommendation: dict) -> dict:
    with (
        security._locked(storage_directory(directory)) as root,
        _browser(root) as session,
    ):
        binding = _binding(root, season)
        if not isinstance(recommendation, dict):
            raise AccountError("Predict recommendation must be an object")
        live = _snapshot(
            session,
            binding,
            recommendation.get("gameday_id"),
            recommendation.get("scope", "round"),
        )
        rows = _journal(root)
        pending = [r for r in rows if r["status"] != "verified"]
        # Recover uncertain writes even if the original proposal has since expired.
        if pending:
            row = pending[-1]
            canonical = {k: recommendation.get(k) for k in row["recommendation"]}
            if isinstance(canonical.get("answers"), list):
                try:
                    canonical["answers"] = sorted(
                        [
                            {
                                k: r[k]
                                for k in (
                                    "question_id",
                                    "selected_options",
                                    "booster_id",
                                )
                            }
                            for r in canonical["answers"]
                        ],
                        key=lambda r: r["question_id"],
                    )
                except (KeyError, TypeError):
                    raise AccountError("Malformed pending Predict proposal") from None
            saved = {
                **row["recommendation"],
                "answers": sorted(
                    row["recommendation"]["answers"], key=lambda r: r["question_id"]
                ),
            }
            if canonical != saved:
                raise AccountError(
                    "Unfinished Predict journal; use recover before a different proposal"
                )
            return _run(root, rows, row, session, binding, live)
        if _EXPECTED.get() is not None and _precondition(live) != _EXPECTED.get():
            raise AccountError(
                "Predict scheduled precondition changed before submission; no overwrite"
            )
        target = _recommendation(recommendation, live)
        key = _digest(
            {"binding": binding_fingerprint(binding), "recommendation": target}
        )
        previous = next((r for r in rows if r["key"] == key), None)
        if previous:
            return _run(root, rows, previous, session, binding, live)
        steps = _steps(live, target["answers"])
        if steps:
            _writable(live)
        row = {
            "key": key,
            "binding": binding_fingerprint(binding),
            "status": "ready",
            "at": _now().isoformat(),
            "frame": _frame(live),
            "recommendation": target,
            "expected": target["answers"],
            "steps": steps,
        }
        rows.append(row)
        _save(root, rows)
        return _run(root, rows, row, session, binding, live)


def _recovery_matches(row, expected):
    actual = {
        "binding_fingerprint": row["binding"],
        **{
            key: row["frame"][key]
            for key in (
                "season",
                "gameday_id",
                "race_id",
                "scope",
                "question_fingerprint",
            )
        },
        "answers": row["expected"],
    }
    required = {
        "binding_fingerprint",
        "season",
        "gameday_id",
        "race_id",
        "scope",
        "answers",
    }
    return (
        isinstance(expected, dict)
        and required <= expected.keys() <= actual.keys()
        and all(
            type(value) is type(actual[key]) and value == actual[key]
            for key, value in expected.items()
        )
    )


def recover(
    directory: Path,
    season: int,
    gameday_id: int | None = None,
    scope: str = "round",
    *,
    expected: dict | None = None,
) -> dict:
    """Reconcile/resume a journal, optionally constrained to a scheduler target.

    ``expected`` requires binding_fingerprint, season, gameday_id, race_id,
    scope and answers; question_fingerprint is optional. A pending mismatch
    fails before readback or any ready step. Default no-pending behavior remains
    a fresh snapshot with apply_status='nothing_to_recover'.
    """
    with (
        security._locked(storage_directory(directory)) as root,
        _browser(root) as session,
    ):
        binding = _binding(root, season)
        rows = _journal(root)
        row = next((r for r in reversed(rows) if r["status"] != "verified"), None)
        if expected is not None:
            if row is not None and not _recovery_matches(row, expected):
                raise AccountError(
                    "Pending Predict journal differs from expected recovery target; no submission"
                )
            if row is None:
                row = next(
                    (r for r in reversed(rows) if _recovery_matches(r, expected)), None
                )
            if row is None or not _recovery_matches(row, expected):
                raise AccountError(
                    "No Predict journal matches expected recovery target"
                )
        if row is None:
            return {
                **_snapshot(session, binding, gameday_id, scope),
                "apply_status": "nothing_to_recover",
            }
        if gameday_id is not None and (
            row["frame"]["gameday_id"] != gameday_id or row["frame"]["scope"] != scope
        ):
            raise AccountError("Pending Predict journal targets another scope/event")
        live = _snapshot(
            session, binding, row["frame"]["gameday_id"], row["frame"]["scope"]
        )
        return _run(root, rows, row, session, binding, live)


def audit(directory: Path) -> list[dict]:
    with security._locked(storage_directory(directory)) as root:
        return [
            {
                "key": row["key"],
                "status": row["status"],
                "at": row["at"],
                "season": row["frame"]["season"],
                "gameday_id": row["frame"]["gameday_id"],
                "scope": row["frame"]["scope"],
                "steps": [
                    {
                        "question_id": step["payload"]["Predictions"][0]["QuestionId"],
                        "status": step["status"],
                    }
                    for step in row["steps"]
                ],
            }
            for row in _journal(root)
        ]
