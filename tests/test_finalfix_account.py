"""Shipped Final Fix contracts exercised offline; no chip is spent by these tests."""

from copy import deepcopy
from types import SimpleNamespace

import pytest

from f1fantasy import account
from test_account import catalog, fixture, raw, history, state, proposal, install


def session_fixtures():
    common = dict(
        Season="2026",
        GamedayId=19,
        PhaseId=1,
        IsPostponed=0,
        GDIsCurrent=1,
        GDIsLocked=1,
        MDIsLocked=0,
        MHIsLocked=0,
        IsFinalFixActive=1,
    )
    return [
        dict(
            common, SessionType="Qualifying", MatchStatus="4", RaceDay=43, MDIsCurrent=0
        ),
        dict(common, SessionType="Race", MatchStatus="1", RaceDay=44, MDIsCurrent=1),
    ]


def ready(state):
    result = deepcopy(state)
    result.update(
        locked=True,
        active_chip=None,
        eligible_chips=["final_fix"],
        final_fix_window=account._final_fix_window(
            session_fixtures(), session_fixtures()[1]
        ),
        retained_sessions=["Qualifying"],
        accrued_points=8.0,
        retained_points={
            i: {"Qualifying": 1.0} for i in state["drivers"] + state["constructors"]
        },
    )
    return result


def target(state, outgoing="1", incoming="6"):
    ids = state["drivers"] + state["constructors"]
    return dict(
        season=2026,
        gameday_id=19,
        drivers=[incoming if i == outgoing else i for i in state["drivers"]],
        constructors=[incoming if i == outgoing else i for i in state["constructors"]],
        boost_driver_id=incoming
        if outgoing == state["boost_driver_id"]
        else state["boost_driver_id"],
        chip="final_fix",
        x3_driver_id=None,
        budget_tenths_m=1000,
        baseline_ids=state["baseline_ids"],
        expected_transfer_penalty=0,
        outgoing_id=outgoing,
        incoming_id=incoming,
        original_ids=ids,
        original_boost_driver_id=state["boost_driver_id"],
        window=state["final_fix_window"],
        retained_points=state["retained_points"],
    )


def test_exact_scalar_payload_and_retained_multiplier(state, catalog):
    before = ready(state)
    path, payload, expected = account._plan(
        before, catalog, account._proposal(target(before)), False
    )
    assert path == account.BOOSTER + "applyfinalfix"
    assert payload == dict(
        account.PLATFORM,
        teamNo=2,
        gamedayId=19,
        boosterId=3,
        phaseId=1,
        playerId=6,
        playerSkill=1,
        oldPlayerId=1,
        oldPlayerSkill=1,
        raceday=44,
        raceCategoryId="R",
    )
    assert expected["boost_driver_id"] == "6"
    assert expected["final_fix"]["original_boost_driver_id"] == "1"
    assert expected["retained_points"] == before["retained_points"]
    assert expected["transfers_left"] == before["transfers_left"]
    assert expected["net_transfers"] == before["net_transfers"]


@pytest.mark.parametrize(
    "change", ["old", "two", "boost", "window", "points", "chip", "baseline"]
)
def test_final_fix_conflicts_do_not_plan(state, catalog, change):
    before = ready(state)
    p = deepcopy(target(before))
    if change == "old":
        p["outgoing_id"] = "9"
    if change == "two":
        p["drivers"][1] = "7"
    if change == "boost":
        p["boost_driver_id"] = "2"
    if change == "window":
        p["window"]["raceday"] = 45
    if change == "points":
        p["retained_points"]["1"]["Qualifying"] = 2.0
    if change == "chip":
        before["active_chip"] = "x3"
    if change == "baseline":
        p["baseline_ids"] = ["1", "2", "3", "4", "7", "11", "12"]
    with pytest.raises(account.AccountError):
        account._plan(before, catalog, account._proposal(p), False)


def test_constructor_replacement_has_no_multiplier_change(state, catalog):
    before = ready(state)
    _, payload, expected = account._plan(
        before, catalog, account._proposal(target(before, "11", "13")), False
    )
    assert payload["playerSkill"] == payload["oldPlayerSkill"] == 2
    assert expected["boost_driver_id"] == "1"


def test_eight_scoring_entries_normalize_to_effective_seven(
    raw, fixture, catalog, history
):
    raw.update(
        boosterid=3,
        isfinalfixtaken=3,
        finalfixtakengd=19,
        finalfxoldplayerid=1,
        finalfxnewplayerid=6,
        finalfxracecat="R",
        finalfxraceday=44,
        capplayerid=6,
    )
    raw["playerid"].append(dict(id=6, playerpostion=8))
    state = account._normalize(raw, fixture, catalog, history, None)
    assert state["drivers"] == ["6", "2", "3", "4", "5"]
    assert state["net_transfers"] == 0
    assert state["transfers_left"] == 2
    assert state["boost_driver_id"] == "6"
    assert state["final_fix"]["original_ids"] == ["1", "11", "12", "2", "3", "4", "5"]
    raw["finalfxoldplayerid"] = 9
    with pytest.raises(account.AccountError, match="identities"):
        account._normalize(raw, fixture, catalog, history, None)


def evidence_session(catalog):
    fixtures = session_fixtures()
    rows = [
        dict(
            PlayerId=i,
            Value=v["price"] / 10,
            SessionWisePoints=[
                dict(sessiontype="Qualifying", points=1),
                dict(sessiontype="Race", points=None),
            ],
        )
        for i, v in catalog.items()
    ]
    return (
        SimpleNamespace(
            get=lambda path: (
                {"Data": {"fixtures": fixtures}}
                if "schedule" in path
                else {"Data": {"Value": rows}}
            )
        ),
        fixtures,
        rows,
    )


def test_authoritative_window_and_official_retained_points(
    state, raw, catalog, history
):
    session, fixtures, rows = evidence_session(catalog)
    history[0].update(ftMdid=18)
    history[0]["mddetails"]["19"]["mds"] = 2
    account._final_fix_evidence(session, raw, state, catalog, history)
    assert state["accrued_points"] == 8.0
    assert state["final_fix_window"]["remaining_sessions"] == ["race"]
    assert "final_fix" in state["eligible_chips"]
    rows[0]["SessionWisePoints"][0]["points"] = None
    with pytest.raises(account.AccountError, match="points unavailable"):
        account._final_fix_evidence(session, raw, state, catalog, history)


@pytest.mark.parametrize("change", ["closed", "live", "lock", "qualifying"])
def test_scheduled_dates_cannot_open_a_final_fix_window(change):
    fixtures = session_fixtures()
    current = fixtures[1]
    if change == "closed":
        current["IsFinalFixActive"] = 0
    if change == "live":
        current["MatchStatus"] = "2"
    if change == "lock":
        current["MDIsLocked"] = 1
    if change == "qualifying":
        current["SessionType"] = "Qualifying"
    assert not account._final_fix_window(fixtures, current)["open"]


def test_sprint_remaining_session_boundary_is_remote_not_time_based():
    fixtures = session_fixtures()
    fixtures[1].update(SessionType="Sprint Qualifying")
    fixtures.append(
        dict(
            fixtures[1], SessionType="Race", MatchStatus="0", RaceDay=45, MDIsCurrent=0
        )
    )
    assert account._final_fix_window(fixtures, fixtures[1])["remaining_sessions"] == [
        "sprint",
        "race",
    ]


def test_durable_final_fix_timeout_readback_and_repeat(
    tmp_path, monkeypatch, state, catalog
):
    before = ready(state)
    p = target(before)
    _, _, expected = account._plan(before, catalog, account._proposal(p), False)
    after = dict(before, **expected)
    session = install(monkeypatch, tmp_path, [before, after], catalog)
    checks = []
    session.check_final_fix = lambda s: checks.append(s["final_fix_window"])
    session.post_error = True
    assert account.apply_final_fix(tmp_path, 2026, p)["apply_status"] == "verified"
    assert len(checks) == 2
    assert len(session.posts) == 1
    assert account.apply_final_fix(tmp_path, 2026, p)["apply_status"] == "verified"
    assert len(session.posts) == 1


def test_restart_ambiguous_retained_points_never_replays(
    tmp_path, monkeypatch, state, catalog
):
    before = ready(state)
    p = target(before)
    _, _, expected = account._plan(before, catalog, account._proposal(p), False)
    wrong = dict(before, **expected)
    wrong["accrued_points"] = 9.0
    session = install(monkeypatch, tmp_path, [before, wrong, wrong], catalog)
    session.check_final_fix = lambda s: None
    with pytest.raises(account.AccountError, match="unverified"):
        account.apply_final_fix(tmp_path, 2026, p)
    with pytest.raises(account.AccountError, match="no replay"):
        account.apply_final_fix(tmp_path, 2026, p)
    assert len(session.posts) == 1
    assert account.audit(tmp_path)[0]["status"] == "unknown"


@pytest.mark.parametrize("chip", ["autopilot", "no_negative", "x3"])
def test_active_preweek_chip_roster_edit_is_single_transfer(
    state, catalog, proposal, chip
):
    state.update(active_chip=chip, x3_driver_id="3" if chip == "x3" else None)
    proposal.update(chip=chip, x3_driver_id=state["x3_driver_id"])
    path, payload, _ = account._plan(state, catalog, account._proposal(proposal), False)
    assert path == account.TEAM + "transferteam"
    assert payload["boosterId"] == account.CHIPS[chip]
    if chip == "x3":
        assert payload["mgCaptainPlayerId"] == "3"
    assert len(payload["playerId"]) == 7


def test_context_returns_only_verified_event_assets(
    tmp_path, monkeypatch, state, catalog
):
    before = ready(state)
    install(monkeypatch, tmp_path, [before], catalog)
    weekend = SimpleNamespace(gameday_id=19)
    assets = tuple(
        SimpleNamespace(id=i, kind=v["kind"], price=v["price"])
        for i, v in catalog.items()
    )
    monkeypatch.setattr(account.data, "season_weekends", lambda season: (weekend,))
    monkeypatch.setattr(
        account.data, "load_assets", lambda gameday: (assets, account._now())
    )
    context = account.final_fix_context(tmp_path, 2026)
    assert context["weekend"] is weekend
    assert context["assets"] is assets
    assert context["eligible"] is True
    assert context["remaining_sessions"] == ["race"]
    assert context["accrued_points"] == 8.0
    assert context["state"]["boost_driver_id"] == "1"


def test_remote_window_recheck_stops_a_prepared_request(
    tmp_path, monkeypatch, state, catalog
):
    before = ready(state)
    session = install(monkeypatch, tmp_path, [before], catalog)
    count = 0

    def check(state):
        nonlocal count
        count += 1
        if count == 2:
            raise account.AccountError("Final Fix server window/session changed")

    session.check_final_fix = check
    with pytest.raises(account.AccountError, match="window/session changed"):
        account.apply_final_fix(tmp_path, 2026, target(before))
    assert not session.posts
    assert account.audit(tmp_path)[0]["status"] == "prepared"


def test_post_fix_retained_scores_use_original_not_incoming(
    raw, catalog, history, fixture
):
    raw.update(
        boosterid=3,
        isfinalfixtaken=3,
        finalfixtakengd=19,
        finalfxoldplayerid=1,
        finalfxnewplayerid=6,
        finalfxracecat="R",
        finalfxraceday=44,
        capplayerid=6,
    )
    raw["playerid"].append(dict(id=6, playerpostion=8))
    state = account._normalize(raw, fixture, catalog, history, None)
    session, _, rows = evidence_session(catalog)
    rows[5]["SessionWisePoints"][0]["points"] = 99
    history[0]["ftMdid"] = 19
    account._final_fix_evidence(session, raw, state, catalog, history)
    assert state["accrued_points"] == 8.0
    assert "1" in state["retained_points"] and "6" not in state["retained_points"]
    assert "final_fix" not in state["eligible_chips"]
