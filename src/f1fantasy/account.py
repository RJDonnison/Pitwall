"""One explicitly bound Fantasy team through a private, persistent browser.

Private web-client contracts are deliberately narrow. Missing remote evidence is
an error, never an invitation to reconstruct authentication or a lock deadline.
"""

from __future__ import annotations

from contextlib import contextmanager
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
import fcntl
import hashlib
import json
from math import isfinite
import os
from pathlib import Path
import re
import shutil
import stat
import tempfile
import time
from urllib.parse import quote, urlsplit

from . import data

BASE = "https://fantasy.formula1.com"
TEAM = "/services/user/gameplay/"
BOOSTER = "/services/user/booster/"
CHIPS = {
    "limitless": 1,
    "wildcard": 2,
    "final_fix": 3,
    "autopilot": 4,
    "no_negative": 5,
    "x3": 6,
}
CHIP_FIELDS = {
    "limitless": ("islimitlesstaken", "limitlesstakengd"),
    "wildcard": ("iswildcardtaken", "wildcardtakengd"),
    "final_fix": ("isfinalfixtaken", "finalfixtakengd"),
    "autopilot": ("isautopilottaken", "autopilottakengd"),
    "no_negative": ("isnonigativetaken", "nonigativetakengd"),
    "x3": ("isextradrstaken", "extradrstakengd"),
}
PLATFORM = {"platformId": 1, "platformVersion": "1", "platformCategory": "web"}
READ = re.compile(r"^/services/user/gameplay/([^/]+)/getteam/1/([1-3])/(\d+)/(\d+)$")


class AccountError(data.DataError):
    """Account evidence is absent, inconsistent, expired, or unsafe to replay."""


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _integer(value, label: str, minimum: int = 0) -> int:
    if isinstance(value, bool) or not isinstance(value, (int, str)):
        raise AccountError(f"Unverified {label}")
    if not re.fullmatch(r"-?\d+", str(value)) or int(value) < minimum:
        raise AccountError(f"Unverified {label}")
    return int(value)


def _flag(value, label: str) -> bool:
    if isinstance(value, bool):
        return value
    number = _integer(value, label)
    if number not in (0, 1):
        raise AccountError(f"Unknown {label} flag")
    return bool(number)


def _money(value, label: str, *, signed: bool = False) -> int:
    try:
        if isinstance(value, bool):
            raise ValueError
        amount = Decimal(str(value)) * 10
        if (
            not amount.is_finite()
            or (amount < 0 and not signed)
            or amount != amount.to_integral_value()
        ):
            raise ValueError
        return int(amount)
    except (ValueError, InvalidOperation):
        raise AccountError(f"Unverified {label}") from None


def _ids(value, label: str, count: int | None = None) -> list[str]:
    if not isinstance(value, list) or any(
        not isinstance(item, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", item)
        for item in value
    ):
        raise AccountError(f"Unverified {label}")
    if len(set(value)) != len(value) or (count is not None and len(value) != count):
        raise AccountError(f"Invalid {label} count or duplicates")
    return value


def _server_ids(value, label: str, count: int) -> list[str]:
    if not isinstance(value, list) or any(
        isinstance(item, bool) or not isinstance(item, (str, int)) for item in value
    ):
        raise AccountError(f"Unverified {label}")
    return _ids([str(item) for item in value], label, count)


def _timestamp(value) -> datetime:
    try:
        if not isinstance(value, str):
            raise ValueError
        result = datetime.fromisoformat(value.replace("Z", "+00:00"))
        if result.tzinfo is None:
            raise ValueError
        return result.astimezone(timezone.utc)
    except ValueError:
        raise AccountError("Unverified explicit remote lock timestamp") from None


def _unwrap(body):
    if not isinstance(body, dict) or not isinstance(body.get("Meta"), dict):
        raise AccountError("Unrecognized authenticated response envelope")
    if body["Meta"].get("Success") is not True:
        raise AccountError("Authentication expired or Fantasy rejected the request")
    if not isinstance(body.get("Data"), dict) or "Value" not in body["Data"]:
        raise AccountError("Unrecognized authenticated response value")
    return body["Data"]["Value"]


def _read_json(path: Path):
    try:
        info = path.lstat()
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise AccountError("Account state must be an owned regular file")
        os.chmod(path, 0o600)
        return json.loads(path.read_text())
    except (OSError, ValueError):
        raise AccountError("Cannot read private account state") from None


def _atomic(path: Path, value) -> None:
    fd, name = tempfile.mkstemp(prefix=".account-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True, allow_nan=False)
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(name, path)
        directory_fd = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if os.path.exists(name):
            os.unlink(name)


def _private_directory(path: Path) -> None:
    # Reject symlinks in the supplied path, including existing ancestors.
    for part in (path, *path.parents):
        if part.is_symlink():
            raise AccountError("Account directory must not traverse symlinks")
    path.mkdir(mode=0o700, parents=True, exist_ok=True)
    info = path.stat()
    if not stat.S_ISDIR(info.st_mode) or info.st_uid != os.getuid():
        raise AccountError("Account directory must be owned by the current user")
    os.chmod(path, 0o700)


@contextmanager
def _locked(directory: Path):
    directory = Path(directory).absolute()
    try:
        _private_directory(directory)
        fd = os.open(
            directory / "operation.lock", os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600
        )
    except OSError:
        raise AccountError("Cannot open private account lock/directory") from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid():
            raise AccountError("Private account lock must be an owned regular file")
        os.fchmod(fd, 0o600)
        try:
            fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            raise AccountError("Another account operation owns this profile") from None
        try:
            yield directory
        except OSError:
            raise AccountError(
                "Private account storage unavailable; inspect audit before retrying"
            ) from None
    finally:
        os.close(fd)


def _ledger(directory: Path) -> list[dict]:
    path = directory / "journal.json"
    result = _read_json(path) if path.exists() else []
    if not isinstance(result, list) or any(
        not isinstance(row, dict)
        or row.get("status") not in {"prepared", "unknown", "verified"}
        or not isinstance(row.get("expected"), dict)
        or not isinstance(row.get("key"), str)
        for row in result
    ):
        raise AccountError("Invalid account idempotency journal")
    for row in result:
        if row.get("checksum") != _checksum(row):
            raise AccountError("Account journal integrity check failed; no replay")
        if "steps" in row and (
            not isinstance(row.get("allow_penalties"), bool)
            or not isinstance(row["steps"], list)
            or not row["steps"]
            or any(
                not isinstance(step, dict)
                or step.get("status")
                not in {"ready", "prepared", "unknown", "verified"}
                or any(
                    not isinstance(step.get(key), dict)
                    for key in ("proposal", "before", "expected")
                )
                or not isinstance(step.get("operation"), str)
                for step in row["steps"]
            )
        ):
            raise AccountError("Unrecognized combined apply journal; no replay")
    return result


def _checksum(row: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {key: value for key, value in row.items() if key != "checksum"},
            sort_keys=True,
            allow_nan=False,
        ).encode()
    ).hexdigest()


def _save_ledger(directory: Path, rows: list[dict]) -> None:
    # One atomic file is both the idempotency journal and the sanitized audit.
    for row in rows:
        row["checksum"] = _checksum(row)
    _atomic(directory / "journal.json", rows)


def _binding(directory: Path, season: int) -> dict:
    path = directory / "binding.json"
    if not path.exists():
        raise AccountError("Account is not connected; run account connect")
    result = _read_json(path)
    if not isinstance(result, dict) or result.get("season") != season:
        raise AccountError("Account binding season differs; reconnect explicitly")
    guid = result.get("guid")
    if not isinstance(guid, str) or not re.fullmatch(r"[A-Za-z0-9_-]+", guid):
        raise AccountError("Invalid bound account identity")
    if _integer(result.get("team_number"), "bound team", 1) not in (1, 2, 3):
        raise AccountError("Invalid bound team number")
    return result


def _binding_fingerprint(binding: dict) -> str:
    return hashlib.sha256(
        json.dumps(
            {key: binding[key] for key in ("guid", "season", "team_number")},
            sort_keys=True,
        ).encode()
    ).hexdigest()


def _scheduled_binding(proposal: dict, binding: dict) -> None:
    if proposal.get("scheduled") and proposal["scheduled"][
        "account_binding"
    ] != _binding_fingerprint(binding):
        raise AccountError("Scheduled account binding changed; no submission")


class _Session:
    def __init__(self, context):
        self.context = context
        self.page = context.new_page()
        self.observations: list[dict] = []
        self.auth_failure = False
        self.page.on("response", self._observe)

    def _observe(self, response):
        url = urlsplit(response.url)
        match = (
            READ.fullmatch(url.path) if f"{url.scheme}://{url.netloc}" == BASE else None
        )
        if not match:
            return
        try:
            if response.status != 200:
                raise AccountError("Authentication expired")
            value = _unwrap(response.json())
            self.observations.append(
                {
                    "guid": match[1],
                    "requested_team": int(match[2]),
                    "gameday_id": int(match[3]),
                    "phase_id": int(match[4]),
                    "value": value,
                }
            )
        except Exception:
            # Never include response URLs, headers, bodies, or browser errors in logs.
            self.auth_failure = True

    def observe(self, timeout_seconds: int, *, manual: bool = False) -> dict:
        self.observations.clear()
        self.auth_failure = False
        try:
            self.page.goto(BASE + "/en/my-team", wait_until="domcontentloaded")
            end = time.monotonic() + timeout_seconds
            while time.monotonic() < end:
                if self.auth_failure and not manual:
                    raise AccountError(
                        "Authentication expired or account response malformed; reconnect"
                    )
                if self.observations:
                    # Reject multiple observed accounts rather than taking the last one.
                    if len({item["guid"] for item in self.observations}) != 1:
                        raise AccountError("Conflicting observed account identities")
                    return self.observations[-1]
                self.page.wait_for_timeout(200)
        except AccountError:
            raise
        except Exception:
            raise AccountError(
                "Official browser session unavailable; reconnect manually"
            ) from None
        raise AccountError(
            "No authenticated official getteam response observed; complete login/MFA and reconnect"
        )

    def get(self, path: str):
        try:
            response = self.context.request.get(
                BASE + path,
                params={"buster": time.time_ns()},
                headers={"Cache-Control": "no-cache"},
                timeout=20000,
                max_redirects=0,
                max_retries=0,
            )
            if response.status != 200:
                raise AccountError("Account/feed read failed or authentication expired")
            return response.json()
        except AccountError:
            raise
        except Exception:
            raise AccountError("Cannot verify fresh official response") from None

    def post(self, path: str, payload: dict):
        try:
            response = self.context.request.post(
                BASE + path,
                data=payload,
                timeout=20000,
                max_redirects=0,
                max_retries=0,
            )
            if response.status != 200:
                raise AccountError("Save outcome requires read-back")
            _unwrap(response.json())
        except Exception:
            raise AccountError(
                "Save outcome requires read-back; no automatic retry"
            ) from None

    def check_lock(self, season: int, gameday: int, phase: int) -> None:
        """Re-read the server's current session and lock flags before preparing a save."""
        try:
            fixtures = self.get("/feeds/v2/schedule/raceday_en.json")["Data"][
                "fixtures"
            ]
            fixture = _current_fixture(fixtures, season, gameday, phase)
            if any(
                _flag(fixture[key], key)
                for key in ("GDIsLocked", "MDIsLocked", "MHIsLocked")
            ):
                raise AccountError(
                    "Fantasy team is locked by the current server session"
                )
        except (KeyError, TypeError, ValueError) as exc:
            if isinstance(exc, AccountError):
                raise
            raise AccountError("Cannot verify fresh Fantasy lock status") from None

    def deadline(self) -> str | None:
        # Only explicit, timezone-bearing remote markup in the deadline region.
        # Current public UI has only a countdown, so this intentionally yields None.
        values = self.page.locator(
            'section[aria-label="team lock deadline"] time[datetime]'
        ).evaluate_all(
            "elements => elements.map(element => element.getAttribute('datetime'))"
        )
        if not values:
            return None
        parsed = {_timestamp(value).isoformat() for value in values}
        if len(parsed) != 1:
            raise AccountError("Conflicting explicit remote lock deadlines")
        return parsed.pop()

    def check_final_fix(self, state: dict) -> None:
        fixtures = self.get("/feeds/v2/schedule/raceday_en.json")["Data"]["fixtures"]
        fixture = _current_fixture(
            fixtures, state["season"], state["gameday_id"], state["phase_id"]
        )
        window = _final_fix_window(fixtures, fixture)
        if not window["open"] or window != state["final_fix_window"]:
            raise AccountError(
                "Final Fix server window/session changed; refresh context"
            )


@contextmanager
def _browser(directory: Path):
    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        raise AccountError(
            "Install the optional account dependency: pip install '.[account]'"
        ) from None
    profile = directory / "browser"
    _private_directory(profile)
    with sync_playwright() as playwright:
        options = {"headless": os.environ.get("F1FANTASY_HEADLESS") == "1"}
        executable = (
            os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
            or shutil.which("chromium")
            or shutil.which("chromium-browser")
        )
        if executable:
            options["executable_path"] = executable
        try:
            context = playwright.chromium.launch_persistent_context(
                str(profile), **options
            )
        except Exception:
            raise AccountError(
                "Cannot open dedicated account browser; check Chromium installation, "
                "graphical display and profile lock. Set PLAYWRIGHT_CHROMIUM_PATH "
                "to select the Chromium executable explicitly"
            ) from None
        try:
            yield _Session(context)
        finally:
            context.close()


def _selected(value, team_number: int) -> dict:
    if not isinstance(value, dict) or not isinstance(value.get("userTeam"), list):
        raise AccountError("Unrecognized authenticated userTeam response")
    teams = value["userTeam"]
    numbers = [
        _integer(row.get("teamno"), "server team number", 1)
        for row in teams
        if isinstance(row, dict)
    ]
    if len(numbers) != len(teams) or len(set(numbers)) != len(numbers):
        raise AccountError("Malformed or duplicate server team identities")
    selected = [
        row for row in teams if _integer(row["teamno"], "team number") == team_number
    ]
    if len(selected) != 1:
        raise AccountError(
            "Explicitly selected team was not returned by the official read"
        )
    return selected[0]


def _current_fixture(fixtures, season: int, gameday: int, phase: int) -> dict:
    current = [
        row
        for row in fixtures
        if _integer(row["Season"], "fixture season") == season
        and _integer(row["GamedayId"], "fixture gameday") == gameday
        and _integer(row["PhaseId"], "fixture phase") == phase
        and _flag(row["GDIsCurrent"], "current gameday")
        and _flag(row["MDIsCurrent"], "current session")
    ]
    if len(current) != 1:
        raise AccountError(
            "Cannot establish a unique current bound-season event/session"
        )
    fixture = current[0]
    if _flag(fixture["IsPostponed"], "postponed session"):
        raise AccountError("Current session is postponed")
    return fixture


def _public(
    session: _Session, season: int, gameday: int, phase: int
) -> tuple[dict, dict]:
    try:
        fixtures = session.get("/feeds/v2/schedule/raceday_en.json")["Data"]["fixtures"]
        fixture = _current_fixture(fixtures, season, gameday, phase)
        assets, published = data.load_assets(gameday)
        previous_ends = [
            _timestamp(row["SessionEndDateISO8601"])
            for row in fixtures
            if _integer(row["Season"], "fixture season") == season
            and _integer(row["GamedayId"], "fixture gameday") < gameday
            and not _flag(row["IsPostponed"], "postponed session")
        ]
        if previous_ends and published <= max(previous_ends):
            raise AccountError(
                "Live prices predate the previous weekend; recompute after publication"
            )
        statistics = data.load_statistics(season, assets)
        if statistics is None:
            raise AccountError("Fresh statistics cross-check unavailable")
        rows = session.get(f"/feeds/drivers/{gameday}_en.json")["Data"]["Value"]
        roster = {}
        known = {asset.id: asset for asset in assets}
        for row in rows:
            if not _flag(row["IsActive"], "active roster"):
                continue
            id_ = str(row["PlayerId"])
            asset = known.get(id_)
            skill = _integer(row["Skill"], "roster skill", 1)
            if asset is None or id_ in roster or row["PositionName"] != asset.kind:
                raise AccountError("Live roster identity/kind conflict")
            if _money(row["Value"], "live price") != asset.price:
                raise AccountError(
                    "Live prices changed during validation; refresh forecasts"
                )
            roster[id_] = {"kind": asset.kind, "price": asset.price, "skill": skill}
        if set(roster) != set(known):
            raise AccountError("Incomplete fresh roster")
        return fixture, roster
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AccountError):
            raise
        raise AccountError(
            "Cannot verify current schedule, roster and statistics"
        ) from None


def _normalize(raw: dict, fixture: dict, roster: dict, history, deadline) -> dict:
    try:
        season = _integer(fixture["Season"], "season", 1)
        gameday = _integer(fixture["GamedayId"], "gameday", 1)
        number = _integer(raw["teamno"], "team number", 1)
        players = raw["playerid"]
        replacement = None
        if raw.get("boosterid") in (3, "3") and len(players) == 8:
            if raw.get("player_swap_details"):
                raise AccountError(
                    "Final Fix combined with player swaps cannot be reconciled"
                )
            old, new = str(raw["finalfxoldplayerid"]), str(raw["finalfxnewplayerid"])
            all_ids = _server_ids(
                [p["id"] for p in players], "Final Fix scoring lineup", 8
            )
            if old == new or old not in all_ids or new not in all_ids:
                raise AccountError("Invalid Final Fix replacement identities")
            if (
                old not in roster
                or new not in roster
                or roster[old]["kind"] != roster[new]["kind"]
            ):
                raise AccountError("Final Fix replacement kind/roster mismatch")
            outgoing = next(p for p in players if str(p["id"]) == old)
            original = [p for p in players if str(p["id"]) != new]
            original_ids = _server_ids(
                [p["id"] for p in original], "Final Fix original lineup", 7
            )
            players = [
                dict(p, playerpostion=outgoing["playerpostion"])
                if str(p["id"]) == new
                else p
                for p in players
                if str(p["id"]) != old
            ]
            replacement = {
                "outgoing_id": old,
                "incoming_id": new,
                "original_ids": sorted(original_ids),
                "original_boost_driver_id": old
                if str(raw["capplayerid"]) == new
                else str(raw["capplayerid"]),
                "race_category": raw["finalfxracecat"],
                "raceday": _integer(raw["finalfxraceday"], "Final Fix raceday", 1),
            }
            if replacement["race_category"] not in ("R", "S"):
                raise AccountError("Unknown Final Fix scoring boundary")
        elif raw.get("boosterid") in (3, "3") and raw.get("finalfxoldplayerid"):
            raise AccountError("Final Fix retained scoring entry is missing")
        if not isinstance(players, list) or len(players) != 7:
            raise AccountError(
                "Historical/Final Fix/swap lineup cannot be reconciled as seven selections"
            )
        ids = _server_ids([row["id"] for row in players], "server lineup", 7)
        positions = [
            _integer(row["playerpostion"], "player position", 1) for row in players
        ]
        if sorted(positions) != list(range(1, 8)) or any(
            id_ not in roster for id_ in ids
        ):
            raise AccountError(
                "Server lineup positions or live roster cannot be verified"
            )
        ids = [id_ for _, id_ in sorted(zip(positions, ids))]
        drivers = [id_ for id_ in ids if roster[id_]["kind"] == "DRIVER"]
        constructors = [id_ for id_ in ids if roster[id_]["kind"] == "CONSTRUCTOR"]
        _ids(drivers, "server drivers", 5)
        _ids(constructors, "server constructors", 2)
        boost = str(raw["capplayerid"])
        if boost not in drivers:
            raise AccountError("Invalid server Boost allocation")
        baseline = _server_ids(raw["gd_initial_team"], "server net baseline", 7)
        info = raw["team_info"]
        cap = _money(info["maxTeambal"], "team cost cap")
        balance = _money(
            info["teamBal"],
            "remaining team balance",
            signed=raw["boosterid"] in (1, "1"),
        )
        if sum(roster[id_]["price"] for id_ in ids) + balance != cap:
            raise AccountError("Server balance/cap disagrees with newly fetched prices")
        allowance = _integer(info["subsallowed"], "transfer allowance")
        left = _integer(info["userSubsleft"], "remaining transfers", -7)
        accounting = _flag(raw["isaccounting"], "accounting")
        late = _flag(raw["islateonboard"], "late onboarding")
        used, active = {}, []
        for chip, (flag, day) in CHIP_FIELDS.items():
            usage = raw[flag]
            # The service can store the chip's identity here (observed x3: 6),
            # rather than a boolean 1. Other chips' identities remain invalid.
            if not isinstance(usage, bool) and _integer(usage, flag) == CHIPS[chip]:
                usage = 1
            used[chip] = _flag(usage, flag)
            # An unused chip has no activation game day; the service may leave
            # that field null or empty rather than returning the zero sentinel.
            taken_day = (
                0
                if not used[chip] and raw[day] in (None, "")
                else _integer(raw[day], day, 1 if used[chip] else 0)
            )
            if taken_day == gameday:
                if not used[chip]:
                    raise AccountError("Contradictory chip history")
                active.append(chip)
        if len(active) > 1:
            raise AccountError("Multiple active chips")
        active_chip = active[0] if active else None
        booster = (
            0
            if active_chip is None and raw["boosterid"] in (None, "")
            else _integer(raw["boosterid"], "active booster")
        )
        if booster != (CHIPS[active_chip] if active_chip else 0):
            raise AccountError("Ambiguous active versus historical chip identity")
        x3 = str(raw["mgcapplayerid"]) if active_chip == "x3" else None
        if x3 is not None and (x3 not in drivers or x3 == boost):
            raise AccountError("Invalid x3 allocation")
        unlimited = active_chip in {"limitless", "wildcard"} or (
            not accounting and allowance == 0 and left == 0
        )
        net = len(
            set(baseline) - set(replacement["original_ids"] if replacement else ids)
        )
        if not unlimited and (allowance not in (2, 3) or left != allowance - net):
            raise AccountError("Server transfer state conflicts with net baseline")
        if not isinstance(history, list):
            raise AccountError("Unrecognized team history")
        histories = [
            row for row in history if _integer(row["teamno"], "history team") == number
        ]
        if len(histories) != 1:
            raise AccountError("Missing or duplicate selected-team history")
        # Despite its name, mddetails is keyed by Fantasy GamedayId, not the
        # lineup's matchday or the schedule's per-session RaceDay identifier.
        details = histories[0].get("mddetails")
        if not isinstance(details, dict):
            raise AccountError("Unrecognized selected-team game-day history")
        detail = details.get(str(gameday))
        if not isinstance(detail, dict):
            raise AccountError("Missing selected-team history for current game day")
        state = _integer(detail.get("mds"), "team session status")
        if state not in (0, 1, 2, 3):
            raise AccountError("Unknown team session status")
        locked = state != 0 or any(
            _flag(fixture[key], key)
            for key in ("GDIsLocked", "MDIsLocked", "MHIsLocked")
        )
        available = [chip for chip in CHIPS if not used[chip]]
        eligible = [
            chip
            for chip in available
            if chip != "final_fix"
            and not late
            and state == 0
            and not locked
            and not active_chip
            and (chip not in {"limitless", "wildcard"} or accounting)
        ]
        if deadline is not None:
            deadline = _timestamp(deadline).isoformat()
        result = {
            "season": season,
            "team_number": number,
            "gameday_id": gameday,
            "phase_id": _integer(fixture["PhaseId"], "phase", 1),
            "drivers": drivers,
            "constructors": constructors,
            "boost_driver_id": boost,
            "x3_driver_id": x3,
            "budget": cap / 10,
            "budget_tenths_m": cap,
            "remaining_budget_tenths_m": balance,
            "carry": allowance - 2 if allowance in (2, 3) else 0,
            "baseline_ids": baseline,
            "available_chips": available,
            "eligible_chips": eligible,
            "active_chip": active_chip,
            "lock_deadline_utc": deadline,
            "locked": locked,
            "fetched_at": _now().isoformat(),
            "unlimited_transfers": unlimited,
            "net_transfers": net,
            "transfer_allowance": allowance,
            "transfers_left": left,
            "transfer_penalty": 0 if unlimited else max(net - allowance, 0) * 10,
        }
        if replacement is not None:
            result["final_fix"] = replacement
        return result
    except (KeyError, TypeError, ValueError) as exc:
        if isinstance(exc, AccountError):
            raise
        raise AccountError(
            "Authenticated state/history schema cannot be verified"
        ) from None


def _snapshot(
    session: _Session, binding: dict, observation: dict | None = None
) -> tuple[dict, dict]:
    observed = observation if observation is not None else session.observe(30)
    if observed["guid"] != binding["guid"]:
        raise AccountError(
            "Browser account differs from the bound identity; reconnect explicitly"
        )
    gameday, phase = observed["gameday_id"], observed["phase_id"]
    guid = quote(binding["guid"], safe="")
    number = binding["team_number"]
    raw = _selected(
        _unwrap(session.get(f"{TEAM}{guid}/getteam/1/{number}/{gameday}/{phase}")),
        number,
    )
    fixture, roster = _public(session, binding["season"], gameday, phase)
    history = _unwrap(session.get(f"{TEAM}{guid}/getusergamedaysv1/1"))
    state = _normalize(raw, fixture, roster, history, session.deadline())
    if state["active_chip"] == "final_fix" and not state.get("final_fix"):
        raise AccountError(
            "Final Fix retained original/replacement scoring entries unavailable"
        )
    if _flag(fixture.get("IsFinalFixActive", 0), "Final Fix window") or state.get(
        "final_fix"
    ):
        _final_fix_evidence(session, raw, state, roster, history)
    return state, roster


def _final_fix_window(fixtures: list, fixture: dict) -> dict:
    """Server flags/statuses own eligibility; scheduled starts never open a window."""
    event = [
        f
        for f in fixtures
        if str(f["Season"]) == str(fixture["Season"])
        and f["GamedayId"] == fixture["GamedayId"]
        and f["PhaseId"] == fixture["PhaseId"]
    ]
    upcoming = [f for f in event if str(f["MatchStatus"]) in ("0", "1")]
    if any(
        str(f["MatchStatus"]) not in ("0", "1", "2", "3", "4", "5", "6") for f in event
    ):
        raise AccountError("Unknown Final Fix session status")
    if sum(str(f["MatchStatus"]) == "1" for f in event) > 1:
        raise AccountError("Ambiguous current Final Fix session")
    upcoming.sort(key=lambda f: _integer(f["RaceDay"], "session order", 1))
    # The shipped cj/y5 helpers use the CURRENT or next UPCOMING session.
    next_session = next(
        (f for f in upcoming if str(f["MatchStatus"]) == "1"),
        upcoming[0] if upcoming else None,
    )
    names = {"Race": ("race", "R"), "Sprint Qualifying": ("sprint", "S")}
    kind = names.get(next_session["SessionType"]) if next_session else None
    remaining = []
    if kind:
        remaining = [
            names[f["SessionType"]][0]
            for f in upcoming
            if _integer(f["RaceDay"], "session order") >= int(next_session["RaceDay"])
            and f["SessionType"] in names
        ]
        if len(set(remaining)) != len(remaining):
            raise AccountError("Duplicate remaining Final Fix sessions")
    opened = _flag(fixture["IsFinalFixActive"], "Final Fix window")
    live = any(str(f["MatchStatus"]) in ("2", "3", "5") for f in event)
    opened = (
        opened
        and bool(kind)
        and not live
        and not any(_flag(next_session[k], k) for k in ("MDIsLocked", "MHIsLocked"))
        and not any(f["SessionType"] == "Qualifying" for f in upcoming)
    )
    return {
        "open": opened,
        "raceday": _integer(next_session["RaceDay"], "next raceday", 1)
        if kind
        else None,
        "race_category": kind[1] if kind else None,
        "remaining_sessions": remaining,
        "next_raceday": _integer(next_session["RaceDay"], "next raceday", 1)
        if kind
        else None,
    }


def _finite_points(value) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        raise AccountError("Official accrued session points unavailable")
    try:
        result = float(value)
    except ValueError:
        raise AccountError("Malformed official accrued points") from None
    if not isfinite(result):
        raise AccountError("Non-finite official accrued points")
    return result


def _final_fix_evidence(session, raw, state, roster, history) -> None:
    """Attach official retained scoring and server window evidence to a snapshot."""
    try:
        fixtures = session.get("/feeds/v2/schedule/raceday_en.json")["Data"]["fixtures"]
        fixture = _current_fixture(
            fixtures, state["season"], state["gameday_id"], state["phase_id"]
        )
        window = _final_fix_window(fixtures, fixture)
        replacement = state.get("final_fix")
        boundary = (
            replacement["race_category"] if replacement else window["race_category"]
        )
        if boundary not in ("R", "S"):
            raise AccountError("No authoritative remaining Final Fix session")
        event = [
            f
            for f in fixtures
            if str(f["Season"]) == str(state["season"])
            and f["GamedayId"] == state["gameday_id"]
            and f["PhaseId"] == state["phase_id"]
        ]
        event.sort(key=lambda f: _integer(f["RaceDay"], "session order", 1))
        category = {"Qualifying": "Q", "Sprint Qualifying": "S", "Race": "R"}
        cut = next(
            i for i, f in enumerate(event) if category.get(f["SessionType"]) == boundary
        )
        retained = [f["SessionType"] for f in event[:cut]]
        if not retained or any(str(f["MatchStatus"]) != "4" for f in event[:cut]):
            raise AccountError("Prior session scoring is not authoritatively complete")
        ids = (
            replacement["original_ids"]
            if replacement
            else state["drivers"] + state["constructors"]
        )
        boost = (
            replacement["original_boost_driver_id"]
            if replacement
            else state["boost_driver_id"]
        )
        rows = session.get(f"/feeds/drivers/{state['gameday_id']}_en.json")["Data"][
            "Value"
        ]
        scores = {}
        total = 0.0
        for id_ in ids:
            matches = [p for p in rows if str(p["PlayerId"]) == id_]
            if (
                len(matches) != 1
                or _money(matches[0]["Value"], "Final Fix price")
                != roster[id_]["price"]
            ):
                raise AccountError("Final Fix roster/price changed")
            values = {}
            for name in retained:
                points = [
                    p
                    for p in matches[0]["SessionWisePoints"]
                    if p["sessiontype"] == name
                ]
                if len(points) != 1:
                    raise AccountError("Missing/duplicate retained session points")
                values[name] = _finite_points(points[0]["points"])
            scores[id_] = values
            total += sum(values.values()) * (2 if id_ == boost else 1)
        detail = next(h for h in history if int(h["teamno"]) == state["team_number"])
        eligible = (
            window["open"]
            and int(detail["mddetails"][str(state["gameday_id"])]["mds"]) == 2
            and str(detail["ftMdid"]) != str(state["gameday_id"])
            and not _flag(raw["islateonboard"], "late onboarding")
            and state["active_chip"] is None
            and "final_fix" in state["available_chips"]
        )
        state["final_fix_window"] = window
        state["retained_sessions"] = retained
        state["retained_points"] = scores
        state["accrued_points"] = total
        if eligible:
            state["eligible_chips"].append("final_fix")
    except (KeyError, TypeError, ValueError, StopIteration) as exc:
        if isinstance(exc, AccountError):
            raise
        raise AccountError(
            "Cannot verify Final Fix session/window/scoring evidence"
        ) from None


def final_fix_context(directory: Path, season: int) -> dict:
    """Fresh account-aware Final Fix inputs; no forecasts use current-week results."""
    with _locked(directory) as directory:
        binding = _binding(directory, season)
        with _browser(directory) as session:
            state, roster = _snapshot(session, binding)
            if "final_fix_window" not in state:
                raise AccountError(
                    "Final Fix server window is closed or conflicting chip is active"
                )
            weekends = data.season_weekends(season)
            matches = [w for w in weekends if w.gameday_id == state["gameday_id"]]
            if len(matches) != 1:
                raise AccountError("Final Fix original weekend identity unavailable")
            assets, _ = data.load_assets(state["gameday_id"])
            if {a.id: (a.kind, a.price) for a in assets} != {
                k: (v["kind"], v["price"]) for k, v in roster.items()
            }:
                raise AccountError("Final Fix context prices changed; refresh")
            return dict(
                state=state,
                weekend=matches[0],
                assets=assets,
                remaining_sessions=state["final_fix_window"]["remaining_sessions"],
                accrued_points=state["accrued_points"],
                eligible="final_fix" in state["eligible_chips"],
                window=state["final_fix_window"],
            )


def apply_final_fix(directory: Path, season: int, proposal: dict) -> dict:
    """One explicit replacement through the shared durable apply/recovery journal."""
    if not isinstance(proposal, dict) or proposal.get("chip") != "final_fix":
        raise AccountError("Final Fix proposal must explicitly request final_fix")
    return apply(directory, season, proposal)


def connect(
    directory: Path, season: int, team_number: int, timeout_seconds: int = 300
) -> dict:
    """Open official manual login/MFA, observe identity, and bind one existing team."""
    _integer(season, "season", 1)
    if _integer(team_number, "team number", 1) not in (1, 2, 3):
        raise AccountError("Team number must be 1, 2, or 3")
    _integer(timeout_seconds, "login timeout", 1)
    with _locked(directory) as directory, _browser(directory) as session:
        observed = session.observe(timeout_seconds, manual=True)
        binding = {
            "season": season,
            "team_number": team_number,
            "guid": observed["guid"],
        }
        state, _ = _snapshot(session, binding, observed)
        existing = directory / "binding.json"
        if existing.exists() and _read_json(existing) != binding and _ledger(directory):
            raise AccountError(
                "Existing journal belongs to another binding; choose a new account directory"
            )
        _atomic(existing, binding)
        return state


def show(directory: Path, season: int, *, team_number: int | None = None) -> dict:
    """Read a selected team without changing the one-team submission binding."""
    with _locked(directory) as directory:
        binding = _binding(directory, season)
        if team_number is not None:
            if type(team_number) is not int or team_number not in (1, 2, 3):
                raise AccountError("Read-only team number must be 1, 2 or 3")
            binding = dict(binding, team_number=team_number)
        with _browser(directory) as session:
            state, _ = _snapshot(session, binding)
            if state["active_chip"] == "limitless":
                for entry in reversed(_ledger(directory)):
                    expected = entry["expected"]
                    if (
                        entry["status"] == "verified"
                        and entry.get("restoration_ids")
                        and all(
                            expected.get(key) == state.get(key)
                            for key in (
                                "season",
                                "team_number",
                                "gameday_id",
                                "phase_id",
                                "active_chip",
                            )
                        )
                    ):
                        state["limitless_restoration_ids"] = entry["restoration_ids"]
                        break
            return state


def recover(
    directory: Path,
    season: int,
    *,
    confirm_completed: bool = True,
    scheduled: dict | None = None,
) -> dict | None:
    """Reconcile an interrupted write before the CLI attempts a new forecast.

    Chip activation can make an ordinary new plan ineligible. Recovery uses the
    durable plan, verifying uncertain writes before continuing unsent steps.
    A completed chip apply is returned again only if fresh state still matches.
    """
    with _locked(directory) as directory:
        binding = _binding(directory, season)
        rows = _ledger(directory)
        pending = [row for row in rows if row["status"] != "verified"]
        completed_chip = (
            rows[-1]
            if confirm_completed and rows and rows[-1]["expected"].get("active_chip")
            else None
        )
        if not pending and completed_chip is None:
            return None
        with _browser(directory) as session:
            state, roster = _snapshot(session, binding)
            if not pending:
                if _matches(state, completed_chip["expected"]):
                    return dict(
                        state,
                        apply_status="verified",
                        idempotency_key=completed_chip["key"],
                    )
                return None
            for row in pending:
                if "steps" in row:
                    if scheduled is not None and any(
                        step["status"] == "ready"
                        and step["proposal"].get("scheduled") != scheduled
                        for step in row["steps"]
                    ):
                        raise AccountError(
                            "Pending account plan belongs to another scheduling window; reconcile manually"
                        )
                    state = _run_combined(
                        directory, rows, row, session, binding, state, roster
                    )
                else:
                    if not _matches(state, row["expected"]):
                        raise AccountError(
                            "Previous apply outcome conflicts with fresh read-back; no replay or new write"
                        )
                    row.update(status="verified", verified_at=_now().isoformat())
                    _save_ledger(directory, rows)
        return dict(state, apply_status="verified", idempotency_key=pending[-1]["key"])


def _proposal(proposal: dict) -> dict:
    if not isinstance(proposal, dict):
        raise AccountError("Proposal must be an object")
    try:
        result = {
            key: proposal[key]
            for key in (
                "season",
                "gameday_id",
                "drivers",
                "constructors",
                "boost_driver_id",
                "chip",
                "x3_driver_id",
                "budget_tenths_m",
                "baseline_ids",
                "expected_transfer_penalty",
            )
        }
        for key in (
            "season",
            "gameday_id",
            "budget_tenths_m",
            "expected_transfer_penalty",
        ):
            result[key] = _integer(result[key], key)
        result["drivers"] = _ids(result["drivers"], "proposed drivers", 5)
        result["constructors"] = _ids(
            result["constructors"], "proposed constructors", 2
        )
        _ids(result["drivers"] + result["constructors"], "proposed lineup", 7)
        result["baseline_ids"] = sorted(
            _ids(result["baseline_ids"], "proposal baseline", 7)
        )
        if result["boost_driver_id"] not in result["drivers"]:
            raise AccountError("Boost must be a proposed driver")
        if result["chip"] is not None and result["chip"] not in CHIPS:
            raise AccountError("Unknown proposal chip")
        if result["x3_driver_id"] is not None and (
            result["x3_driver_id"] not in result["drivers"]
            or result["x3_driver_id"] == result["boost_driver_id"]
        ):
            raise AccountError("x3 must be a different proposed driver")
        # Selection order is not an idempotency distinction.
        result["drivers"] = sorted(result["drivers"])
        result["constructors"] = sorted(result["constructors"])
        if "scheduled" in proposal:
            guard = proposal["scheduled"]
            if not isinstance(guard, dict):
                raise AccountError("Malformed scheduled apply guard")
            result["scheduled"] = {
                key: _integer(guard.get(key), key, 1)
                for key in ("team_number", "phase_id")
            }
            fingerprint = guard.get("account_binding")
            if not isinstance(fingerprint, str) or not re.fullmatch(
                r"[0-9a-f]{64}", fingerprint
            ):
                raise AccountError("Malformed scheduled account binding")
            result["scheduled"]["account_binding"] = fingerprint
            if result["chip"] != "final_fix":
                for key in ("deadline", "cutoff"):
                    result["scheduled"][key] = _timestamp(guard.get(key)).isoformat()
                if _timestamp(guard["cutoff"]) >= _timestamp(guard["deadline"]):
                    raise AccountError(
                        "Scheduled safety cutoff must precede lock deadline"
                    )
        if result["chip"] == "final_fix":
            if not all(
                key in proposal
                for key in (
                    "outgoing_id",
                    "incoming_id",
                    "original_ids",
                    "original_boost_driver_id",
                    "window",
                    "retained_points",
                )
            ):
                raise AccountError(
                    "Final Fix blocked: explicit replacement and authoritative window evidence required"
                )
            result["outgoing_id"] = _ids(
                [proposal["outgoing_id"]], "Final Fix outgoing", 1
            )[0]
            result["incoming_id"] = _ids(
                [proposal["incoming_id"]], "Final Fix incoming", 1
            )[0]
            result["original_ids"] = sorted(
                _ids(proposal["original_ids"], "Final Fix original lineup", 7)
            )
            result["original_boost_driver_id"] = proposal["original_boost_driver_id"]
            if result["original_boost_driver_id"] not in result["original_ids"]:
                raise AccountError("Invalid Final Fix original Boost")
            for key in ("window", "retained_points"):
                if not isinstance(proposal[key], dict):
                    raise AccountError("Missing Final Fix forecast boundary evidence")
                result[key] = proposal[key]
            # Validate JSON before deriving a durable journal identity.
            json.dumps(result, allow_nan=False)
        return result
    except (KeyError, TypeError):
        raise AccountError("Malformed account proposal") from None
    except ValueError as exc:
        if isinstance(exc, AccountError):
            raise
        raise AccountError("Malformed/non-finite account proposal") from None


def _plan(
    state: dict, roster: dict, proposal: dict, allow_penalties: bool
) -> tuple[str | None, dict, dict]:
    _scheduled_guard(state, proposal)
    if (
        proposal["season"] != state["season"]
        or proposal["gameday_id"] != state["gameday_id"]
    ):
        raise AccountError("Proposal event/season is stale; recompute forecasts")
    if set(proposal["baseline_ids"]) != set(state["baseline_ids"]):
        raise AccountError("Net-transfer baseline changed; recompute forecasts")
    if proposal["budget_tenths_m"] != state["budget_tenths_m"]:
        raise AccountError("Account budget changed; recompute forecasts")
    selected = proposal["drivers"] + proposal["constructors"]
    for kind, ids in (
        ("DRIVER", proposal["drivers"]),
        ("CONSTRUCTOR", proposal["constructors"]),
    ):
        if any(id_ not in roster or roster[id_]["kind"] != kind for id_ in ids):
            raise AccountError("Proposal selections differ from fresh active roster")
    chip = proposal["chip"]
    active = state["active_chip"]
    if active is not None and chip != active:
        raise AccountError("Active chip cannot be cancelled or replaced")
    if chip == "final_fix":
        return _plan_final_fix(state, roster, proposal)
    if chip is not None and chip != active and chip not in state["eligible_chips"]:
        raise AccountError("Requested chip is not verifiably eligible")
    x3 = proposal["x3_driver_id"]
    if (chip == "x3") != (x3 is not None):
        raise AccountError("x3 allocation must match the requested/active x3 chip")
    cost = sum(roster[id_]["price"] for id_ in selected)
    if chip != "limitless" and cost > state["budget_tenths_m"]:
        raise AccountError("Proposed team exceeds the freshly verified account cap")
    net = len(set(state["baseline_ids"]) - set(selected))
    unlimited = state["unlimited_transfers"] or chip in {"limitless", "wildcard"}
    penalty = 0 if unlimited else max(net - state["transfer_allowance"], 0) * 10
    if penalty != proposal["expected_transfer_penalty"]:
        raise AccountError("Transfer penalty changed; recompute forecasts")
    if penalty and not allow_penalties:
        raise AccountError("Paid transfers require allow_penalties=True")
    expected = {
        "season": state["season"],
        "team_number": state["team_number"],
        "gameday_id": state["gameday_id"],
        "phase_id": state["phase_id"],
        "drivers": sorted(proposal["drivers"]),
        "constructors": sorted(proposal["constructors"]),
        "boost_driver_id": proposal["boost_driver_id"],
        "x3_driver_id": x3,
        "active_chip": chip,
        "baseline_ids": sorted(state["baseline_ids"]),
        "budget_tenths_m": state["budget_tenths_m"],
        "remaining_budget_tenths_m": state["budget_tenths_m"] - cost,
        "net_transfers": net,
        "transfer_penalty": penalty,
        "transfer_allowance": state["transfer_allowance"],
        "available_chips": sorted(
            set(state["available_chips"]) - ({chip} if chip else set())
        ),
        "unlimited_transfers": unlimited,
    }
    expected["transfers_left"] = (
        state["transfers_left"] if unlimited else state["transfer_allowance"] - net
    )
    changed = set(selected) != set(state["drivers"] + state["constructors"])
    boost_changed = proposal["boost_driver_id"] != state["boost_driver_id"]
    if (
        chip != active
        and chip in {"autopilot", "no_negative", "x3"}
        and (changed or (chip != "x3" and boost_changed))
    ):
        raise AccountError(
            "Non-atomic chip plus lineup/Boost changes require staged apply"
        )
    if _matches(state, expected):
        return None, {}, expected
    if chip == "limitless" and active != "limitless":
        payload = dict(
            PLATFORM,
            teamNo=state["team_number"],
            tourGameDayId=state["gameday_id"],
            boosterId=1,
            phaseId=state["phase_id"],
            captainPlayerId=proposal["boost_driver_id"],
            playerId=[_wire_id(id_) for id_ in selected],
            position=list(range(1, 8)),
            skill=[roster[id_]["skill"] for id_ in selected],
        )
        return BOOSTER + "applylimitless", payload, expected
    if chip in {"autopilot", "no_negative", "x3"} and (
        chip != active or chip == "x3" and not changed
    ):
        payload = dict(
            PLATFORM,
            teamNo=state["team_number"],
            tourGameDayId=state["gameday_id"],
            boosterId=CHIPS[chip],
            phaseId=state["phase_id"],
        )
        operation = {
            "autopilot": "applydrsenabled",
            "no_negative": "applynonegative",
            "x3": "applymegadriver",
        }[chip]
        if chip == "x3":
            payload.update(
                captainPlayerId=proposal["boost_driver_id"], mgCaptainPlayerId=x3
            )
            if active == "x3":
                operation = "megadriverchange"
                payload.pop("boosterId")
        return BOOSTER + operation, payload, expected
    payload = dict(
        PLATFORM,
        gamedayId=state["gameday_id"],
        phaseId=state["phase_id"],
        captainPlayerid=proposal["boost_driver_id"],
        teamNumber=state["team_number"],
        isWildCard=int(chip == "wildcard"),
    )
    if changed or chip == "wildcard" and active != chip:
        payload.update(
            playerId=[_wire_id(id_) for id_ in selected],
            playerPosition=list(range(1, 8)),
            playerSkill=[roster[id_]["skill"] for id_ in selected],
        )
        if chip is not None:
            payload["boosterId"] = CHIPS[chip]
        if chip == "x3":
            payload["mgCaptainPlayerId"] = x3
        return TEAM + "transferteam", payload, expected
    payload["optType"] = 1
    return TEAM + "captainupdate", payload, expected


def _plan_final_fix(state: dict, roster: dict, proposal: dict):
    if state["active_chip"] is not None or "final_fix" not in state["eligible_chips"]:
        raise AccountError(
            "Final Fix is not eligible in the authoritative server window"
        )
    window = state.get("final_fix_window")
    if not window or not window["open"] or proposal["window"] != window:
        raise AccountError("Final Fix forecast window/session changed; recompute")
    if proposal["retained_points"] != state["retained_points"]:
        raise AccountError("Official retained points changed; recompute Final Fix")
    original = state["drivers"] + state["constructors"]
    old, new = proposal["outgoing_id"], proposal["incoming_id"]
    if (
        set(proposal["original_ids"]) != set(original)
        or proposal["original_boost_driver_id"] != state["boost_driver_id"]
    ):
        raise AccountError("Final Fix original lineup/Boost changed")
    if (
        old not in original
        or new in original
        or new not in roster
        or roster[old]["kind"] != roster[new]["kind"]
    ):
        raise AccountError("Final Fix requires exactly one same-kind replacement")
    selected = proposal["drivers"] + proposal["constructors"]
    if set(selected) != (set(original) - {old}) | {new}:
        raise AccountError("Final Fix requires exactly one replacement")
    for kind, ids in (
        ("DRIVER", proposal["drivers"]),
        ("CONSTRUCTOR", proposal["constructors"]),
    ):
        if any(i not in roster or roster[i]["kind"] != kind for i in ids):
            raise AccountError("Final Fix selection kind mismatch")
    boost = new if old == state["boost_driver_id"] else state["boost_driver_id"]
    if proposal["boost_driver_id"] != boost or proposal["x3_driver_id"] is not None:
        raise AccountError("Final Fix inherits Boost; it cannot reassign multipliers")
    cost = sum(roster[i]["price"] for i in selected)
    if cost > state["budget_tenths_m"]:
        raise AccountError("Final Fix exceeds the verified account cap")
    if proposal["expected_transfer_penalty"] != state["transfer_penalty"]:
        raise AccountError("Final Fix does not alter preweek transfer penalties")
    expected = {
        k: state[k]
        for k in (
            "season",
            "team_number",
            "gameday_id",
            "phase_id",
            "budget_tenths_m",
            "net_transfers",
            "transfer_allowance",
            "transfers_left",
            "transfer_penalty",
            "unlimited_transfers",
            "retained_points",
            "retained_sessions",
            "accrued_points",
        )
    }
    expected.update(
        drivers=sorted(proposal["drivers"]),
        constructors=sorted(proposal["constructors"]),
        boost_driver_id=boost,
        x3_driver_id=None,
        active_chip="final_fix",
        baseline_ids=sorted(state["baseline_ids"]),
        remaining_budget_tenths_m=state["budget_tenths_m"] - cost,
        available_chips=sorted(set(state["available_chips"]) - {"final_fix"}),
        final_fix={
            "outgoing_id": old,
            "incoming_id": new,
            "original_ids": sorted(original),
            "original_boost_driver_id": state["boost_driver_id"],
            "race_category": window["race_category"],
            "raceday": window["raceday"],
        },
    )
    payload = dict(
        PLATFORM,
        teamNo=state["team_number"],
        gamedayId=state["gameday_id"],
        phaseId=state["phase_id"],
        boosterId=3,
        playerId=_wire_id(new),
        playerSkill=roster[new]["skill"],
        oldPlayerId=_wire_id(old),
        oldPlayerSkill=roster[old]["skill"],
        raceday=window["raceday"],
        raceCategoryId=window["race_category"],
    )
    return BOOSTER + "applyfinalfix", payload, expected


def _wire_id(id_: str):
    # Source roster numeric IDs are emitted numerically by the shipped UI.
    return int(id_) if id_.isdigit() else id_


def _matches(state: dict, expected: dict) -> bool:
    for key, value in expected.items():
        actual = state.get(key)
        if key in {"drivers", "constructors", "baseline_ids", "available_chips"}:
            if not isinstance(actual, list) or sorted(actual) != value:
                return False
        elif type(actual) is not type(value) or actual != value:
            return False
    return True


def _combined_steps(state: dict, roster: dict, proposal: dict, allow_penalties: bool):
    """Validate both operations before making any change; spend the chip last."""
    chip = proposal["chip"]
    changed = set(proposal["drivers"] + proposal["constructors"]) != set(
        state["drivers"] + state["constructors"]
    )
    boost_changed = proposal["boost_driver_id"] != state["boost_driver_id"]
    if not (
        state["active_chip"] is None
        and chip in {"autopilot", "no_negative", "x3"}
        and (changed or (chip != "x3" and boost_changed))
    ):
        return None
    lineup = dict(proposal, chip=None, x3_driver_id=None)
    steps = []
    for target in (lineup, proposal):
        path, _, expected = _plan(state, roster, target, allow_penalties)
        before = {
            key: sorted(state[key]) if isinstance(value, list) else state[key]
            for key, value in expected.items()
        }
        steps.append(
            {
                "proposal": target,
                "before": before,
                "expected": expected,
                "operation": path.rsplit("/", 1)[-1],
                "status": "ready",
            }
        )
        state = dict(state, **expected)
    return steps


def _scheduled_guard(state: dict, proposal: dict) -> None:
    guard = proposal.get("scheduled")
    if guard is None:
        return
    if any(state[key] != guard[key] for key in ("team_number", "phase_id")):
        raise AccountError("Scheduled team/session changed; no submission")
    if proposal["chip"] != "final_fix" and (
        state.get("lock_deadline_utc") is None
        or _timestamp(state["lock_deadline_utc"]) != _timestamp(guard["deadline"])
        or _now() >= _timestamp(guard["cutoff"])
    ):
        raise AccountError(
            "Scheduled deadline changed or safety cutoff passed; no submission"
        )


def _preflight(session, state: dict, *, final_fix: bool = False) -> None:
    if final_fix:
        session.check_final_fix(state)
        return
    deadline = state["lock_deadline_utc"]
    if state["locked"] or (deadline is not None and _timestamp(deadline) <= _now()):
        raise AccountError("Fantasy team is locked or the verified deadline has passed")
    session.check_lock(state["season"], state["gameday_id"], state["phase_id"])


def _run_combined(directory, rows, row, session, binding, state, roster) -> dict:
    """Resume only unsent operations; an ambiguous sent operation is never replayed."""
    try:
        for step in row["steps"]:
            if step["status"] == "verified":
                continue
            if step["status"] in {"prepared", "unknown"}:
                if not _matches(state, step["expected"]):
                    raise AccountError(
                        "Previous step outcome conflicts with fresh read-back; no replay"
                    )
            else:
                _scheduled_binding(step["proposal"], binding)
                if not _matches(state, step["before"]):
                    raise AccountError(
                        "Account changed between combined apply steps; no new write"
                    )
                path, payload, expected = _plan(
                    state, roster, step["proposal"], row["allow_penalties"]
                )
                if expected != step["expected"]:
                    raise AccountError(
                        "Combined apply prices or accounting changed; no new write"
                    )
                _preflight(session, state)
                step.update(status="prepared", prepared_at=_now().isoformat())
                _save_ledger(directory, rows)
                try:
                    _scheduled_guard(state, step["proposal"])
                except AccountError:
                    step["status"] = "ready"
                    raise
                deadline = state["lock_deadline_utc"]
                if deadline is not None and _timestamp(deadline) <= _now():
                    # No request has been sent, so this step remains safe to resume.
                    step["status"] = "ready"
                    raise AccountError(
                        "Deadline passed before sending combined apply step"
                    )
                try:
                    session.post(path, _numeric_payload(payload))
                except AccountError:
                    pass
                try:
                    state, roster = _snapshot(session, binding)
                    if not _matches(state, expected):
                        raise AccountError("Read-back mismatch")
                except Exception:
                    step["status"] = "unknown"
                    raise AccountError(
                        "Step read-back unverified; no automatic retry"
                    ) from None
            step.update(status="verified", verified_at=_now().isoformat())
            _save_ledger(directory, rows)
        if not _matches(state, row["expected"]):
            raise AccountError("Final combined apply read-back conflicts; no new write")
    except AccountError as exc:
        row["status"] = "unknown"
        _save_ledger(directory, rows)
        completed = [
            step["operation"] for step in row["steps"] if step["status"] == "verified"
        ]
        progress = ", ".join(completed) if completed else "none verified"
        raise AccountError(
            f"Combined apply incomplete (completed: {progress}): {exc}. "
            "Run account apply again to reconcile/resume the saved plan"
        ) from None
    row.update(status="verified", verified_at=_now().isoformat())
    _save_ledger(directory, rows)
    return state


def apply(
    directory: Path, season: int, proposal: dict, allow_penalties: bool = False
) -> dict:
    """Validate a fresh proposal and verify each journaled operation by read-back.

    An unresolved journal entry is never submitted again, even if read-back still
    shows the old team. Main must recompute forecasts before calling after a
    conflict; this layer validates live state/prices, not forecast quality. Combined
    lineup/chip saves resume only operations that were never sent.
    """
    proposal = _proposal(proposal)
    if proposal["season"] != season:
        raise AccountError("Proposal season differs from requested account season")
    with _locked(directory) as directory:
        binding = _binding(directory, season)
        _scheduled_binding(proposal, binding)
        key = hashlib.sha256(
            json.dumps(
                {"binding": binding, "proposal": proposal}, sort_keys=True
            ).encode()
        ).hexdigest()
        rows = _ledger(directory)
        with _browser(directory) as session:
            state, roster = _snapshot(session, binding)
            # Recovery precedes ordinary preflight (deadline/eligibility may have passed).
            for row in rows:
                if row["status"] != "verified" or row["key"] == key:
                    if row["status"] != "verified" and "steps" in row:
                        after = _run_combined(
                            directory, rows, row, session, binding, state, roster
                        )
                        return dict(
                            after, apply_status="verified", idempotency_key=row["key"]
                        )
                    if not _matches(state, row["expected"]):
                        raise AccountError(
                            "Previous apply outcome conflicts with fresh read-back; no replay or new write"
                        )
                    row.update(status="verified", verified_at=_now().isoformat())
                    _save_ledger(directory, rows)
                    if row["key"] == key:
                        return dict(state, apply_status="verified", idempotency_key=key)
            steps = _combined_steps(state, roster, proposal, allow_penalties)
            if steps is not None:
                row = {
                    "key": key,
                    "status": "prepared",
                    "operation": "combined",
                    "prepared_at": _now().isoformat(),
                    "expected": steps[-1]["expected"],
                    "allow_penalties": bool(allow_penalties),
                    "steps": steps,
                }
                rows.append(row)
                _save_ledger(directory, rows)
                after = _run_combined(
                    directory, rows, row, session, binding, state, roster
                )
                return dict(after, apply_status="verified", idempotency_key=key)
            path, payload, expected = _plan(state, roster, proposal, allow_penalties)
            if path is None:
                rows.append(
                    {
                        "key": key,
                        "status": "verified",
                        "operation": "none",
                        "prepared_at": _now().isoformat(),
                        "verified_at": _now().isoformat(),
                        "expected": expected,
                    }
                )
                _save_ledger(directory, rows)
                return dict(state, apply_status="unchanged", idempotency_key=key)
            deadline = state["lock_deadline_utc"]
            _preflight(session, state, final_fix=proposal["chip"] == "final_fix")
            row = {
                "key": key,
                "status": "prepared",
                "prepared_at": _now().isoformat(),
                "operation": path.rsplit("/", 1)[-1],
                "expected": expected,
            }
            if proposal["chip"] == "limitless" and state["active_chip"] is None:
                # This is the team immediately before activation, not the older
                # gd_initial_team used to count net transfers.
                row["restoration_ids"] = sorted(
                    state["drivers"] + state["constructors"]
                )
            rows.append(row)
            _save_ledger(directory, rows)
            # Recheck after durable prepare, immediately before sending.
            _scheduled_guard(state, proposal)
            if (
                proposal["chip"] != "final_fix"
                and deadline is not None
                and _timestamp(deadline) <= _now()
            ):
                row["status"] = "unknown"
                _save_ledger(directory, rows)
                raise AccountError(
                    "Deadline passed after prepare; read-back required, no replay"
                )
            if proposal["chip"] == "final_fix":
                # Re-read the remote window after durable prepare as well.
                session.check_final_fix(state)
            try:
                session.post(path, _numeric_payload(payload))
            except AccountError:
                pass  # HTTP failure/timeout can still mean committed; read first.
            try:
                after, _ = _snapshot(session, binding)
                if not _matches(after, expected):
                    raise AccountError(
                        "Read-back mismatch; apply outcome unknown, no automatic retry"
                    )
            except Exception:
                row["status"] = "unknown"
                _save_ledger(directory, rows)
                raise AccountError(
                    "Apply read-back unverified; journal retained, no automatic retry"
                ) from None
            row.update(status="verified", verified_at=_now().isoformat())
            _save_ledger(directory, rows)
            return dict(after, apply_status="verified", idempotency_key=key)


def _numeric_payload(payload: dict) -> dict:
    return {
        key: _wire_id(value)
        if key in {"captainPlayerid", "captainPlayerId", "mgCaptainPlayerId"}
        else value
        for key, value in payload.items()
    }


def audit(directory: Path) -> list[dict]:
    """Read the sanitized durable apply journal; never launches a browser."""
    with _locked(directory) as directory:
        rows = _ledger(directory)
        entries = [
            {
                key: value
                for key, value in row.items()
                if key
                in {
                    "key",
                    "status",
                    "prepared_at",
                    "verified_at",
                    "operation",
                    "expected",
                }
            }
            for row in rows
        ]
        for entry, row in zip(entries, rows):
            if "steps" in row:
                entry["steps"] = [
                    {
                        key: value
                        for key, value in step.items()
                        if key
                        in {
                            "operation",
                            "status",
                            "prepared_at",
                            "verified_at",
                            "expected",
                        }
                    }
                    for step in row["steps"]
                ]
        return entries
