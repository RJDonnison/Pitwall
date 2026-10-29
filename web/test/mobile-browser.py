"""Manual production-browser regression: run against a fresh local Pages preview.

python web/test/mobile-browser.py http://127.0.0.1:4174/Pitwall/
Requires the optional Playwright Python extra and system Chromium. No account API
or submission is used. Screenshots are written under /tmp/opencode.
"""

import json
import os
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path
import shutil
from urllib.request import urlopen

from playwright.sync_api import sync_playwright


def main():
    url = sys.argv[1] if len(sys.argv) > 1 else "http://127.0.0.1:4174/Pitwall/"
    with urlopen(url + "forecast.json", timeout=20) as response:
        data = json.load(response)
    selected = []
    for kind, count in (("DRIVER", 5), ("CONSTRUCTOR", 2)):
        rows = sorted(
            (a for a in data["assets"] if a["kind"] == kind),
            key=lambda a: a["price_tenths_m"],
        )
        selected.extend(a["id"] for a in rows[:count])
    profile = dict(
        name="Mobile test",
        season=data["season"],
        selected=selected,
        budget=1000,
        carry=0,
        chips=[],
        completed=True,
        initial=False,
        allowPenalties=True,
        active="",
        restore=[],
    )
    empty = dict(profile, selected=[])
    screenshots = Path("/tmp/opencode")
    with sync_playwright() as p:
        browser = p.chromium.launch(
            executable_path=os.environ.get("PLAYWRIGHT_CHROMIUM_PATH")
            or shutil.which("chromium"),
            headless=True,
        )
        try:
            context = browser.new_context(
                viewport={"width": 390, "height": 844}, reduced_motion="reduce"
            )
            context.add_init_script(
                "localStorage.setItem('pitwall-teams-v1', "
                + json.dumps(json.dumps([profile, empty, empty]))
                + ");"
            )
            page = context.new_page()
            errors, writes, workers = [], [], []
            page.on("pageerror", lambda e: errors.append(str(e)))
            page.on(
                "request",
                lambda r: (
                    writes.append(r.url) if r.method not in ("GET", "HEAD") else None
                ),
            )
            page.on("worker", lambda w: workers.append(w.url))
            # The official feeds are currently CORS-blocked on Pages; test this
            # automatic snapshot-preview path deterministically, without logins.
            page.route("https://fantasy.formula1.com/**", lambda r: r.abort())
            page.goto(url + "#garage", wait_until="networkidle")
            page.wait_for_function(
                "document.querySelector('#planning-status')?.textContent === 'Strategy up to date'",
                timeout=130000,
            )
            assert page.url.endswith("#garage"), "Automatic solve moved the user"
            assert (
                page.locator("#optimize,#replan,#refresh,#preview-consent").count() == 0
            )
            assert page.locator("#page-garage a[href='#strategy']").count() == 0
            assert page.locator(".chip-toggle small").count() == 0
            assert page.locator("#roster-board [data-remove]").count() == 7
            assert page.locator("[data-nav=garage]").text_content().strip() == "Garage"
            assert page.locator("#page-garage h1").text_content() == "Garage"
            assert page.locator(".market-card .registry-estimate").count() == len(
                data["assets"]
            )
            assert page.locator(".registry-add svg").count() == len(data["assets"])
            assert page.locator("#active-setup + .import-export").count() == 1
            # Filtering still works after placing the controls beside search.
            page.locator("[data-kind=CONSTRUCTOR]").click()
            assert page.locator(".market-card").count() == sum(
                a["kind"] == "CONSTRUCTOR" for a in data["assets"]
            )
            page.locator("[data-kind=ALL]").click()
            page.evaluate("location.hash='asset-registry'")
            page.wait_for_timeout(100)
            page.evaluate(
                "window.scrollTo(0, document.querySelector('[data-chip=no_negative]').getBoundingClientRect().top + scrollY - 140)"
            )
            before = page.evaluate("scrollY")
            page.locator("[data-chip=no_negative]").click()
            after = page.evaluate("scrollY")
            assert abs(after - before) < 18, ("Chip toggle jumped", before, after)
            assert (
                page.evaluate("document.activeElement?.dataset.chip") == "no_negative"
            )
            page.wait_for_function(
                "document.querySelector('#planning-status')?.textContent === 'Strategy up to date'",
                timeout=130000,
            )
            assert len(workers) >= 2, "Input changes did not recalculate"
            # New publication automatically replaces and recalculates the plan.
            updated = json.loads(json.dumps(data))
            updated["generated_at"] = datetime.now(timezone.utc).isoformat()
            page.route("**/forecast.json*", lambda r: r.fulfill(json=updated))
            count = len(workers)
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_function(
                "document.querySelector('#planning-status')?.textContent === 'Updating strategy…'",
                timeout=15000,
            )
            page.wait_for_function(
                "document.querySelector('#planning-status')?.textContent === 'Strategy up to date'",
                timeout=130000,
            )
            assert len(workers) > count
            for width in (1440, 768, 390, 320):
                page.set_viewport_size(
                    {"width": width, "height": 900 if width > 650 else 844}
                )
                for route in ("garage", "strategy", "insights"):
                    page.evaluate("location.hash=" + json.dumps(route))
                    page.wait_for_timeout(100)
                    overflow = page.evaluate(
                        "[...document.querySelectorAll('main *,header *,footer *')].filter(e => {const r=e.getBoundingClientRect();return r.width && r.right>innerWidth+1 && getComputedStyle(e).position !== 'fixed'}).slice(0,12).map(e=>({tag:e.tagName,cls:e.className,right:e.getBoundingClientRect().right,text:e.textContent.slice(0,70)}))"
                    )
                    page.screenshot(
                        path=str(screenshots / f"mobile-final-{route}-{width}.png"),
                        full_page=True,
                    )
                    assert page.evaluate(
                        "document.documentElement.scrollWidth <= innerWidth"
                    ), (width, route, overflow)
                    if route == "garage":
                        assert page.locator(".market-card.selected").first.evaluate(
                            "e => parseFloat(getComputedStyle(e).borderLeftWidth) >= 2"
                        ), "Selected assets need a clear team-colour border"
                        assert page.locator(".registry-add").first.evaluate(
                            "e => e.getBoundingClientRect().height <= 32 && parseFloat(getComputedStyle(e, '::after').height) >= 44"
                        ), "Compact Add buttons must retain a touch-sized hit area"
                        assert page.evaluate(
                            "Math.abs(document.querySelector('#search').getBoundingClientRect().top - document.querySelector('.market-tools .segments').getBoundingClientRect().top) < 6"
                        ), (width, "Registry search and filters are not inline")
                        if width == 1440:
                            assert page.evaluate(
                                "Math.abs(document.querySelector('#active-setup summary').getBoundingClientRect().top - document.querySelector('#export-team').getBoundingClientRect().top) < 6"
                            ), "Import/export are not inline with chip setup"
                    if route == "strategy":
                        assert page.locator(".race-context .circuit-art").count() == 1
                        assert page.locator(".race-context").count() == 1
                        assert (
                            "Track spec" in page.locator(".race-context").text_content()
                        )
                        assert page.locator(".footer-columns > section").count() == 3
                        assert page.locator("#publication-status").count() == 1
                        assert (
                            "Price snapshot"
                            in page.locator("#publication-status").text_content()
                        )
                        assert (
                            "UTC" in page.locator("#publication-status").text_content()
                        )
                        assert page.locator(".footer-columns p").first.evaluate(
                            "e => 12 <= parseFloat(getComputedStyle(e).fontSize) <= 14"
                        )
                        if width == 1440:
                            assert page.locator(".chip-directive").evaluate(
                                "e => e.getBoundingClientRect().height < 340"
                            ), (
                                "Chip allocation should fit its content, not stretch to the transfer card"
                            )
                            assert page.locator(".race-overview").evaluate(
                                "e => getComputedStyle(e).gap === '0px' && getComputedStyle(e).overflow === 'hidden'"
                            ), (
                                "Race photo, map and context must share one integrated hero"
                            )
                        if width == 1440:
                            assert page.locator("#strategy table").is_visible(), (
                                "Desktop breakdown stayed collapsed after resizing"
                            )
                            row = page.locator("#strategy tbody tr").first
                            color = row.evaluate(
                                "e => getComputedStyle(e).backgroundColor"
                            )
                            row.hover()
                            assert (
                                row.evaluate("e => getComputedStyle(e).backgroundColor")
                                == color
                            ), (
                                "Non-interactive recommendation rows should not change on hover"
                            )
                        assert page.locator(
                            ".roster-directive .transfer-lists"
                        ).evaluate(
                            "e => e.clientHeight <= 185 && getComputedStyle(e).overflowY === 'auto' && e.scrollHeight > e.clientHeight"
                        ), (
                            "Transfers should scroll instead of stretching adjacent cards"
                        )
                        assert (
                            page.locator(".roster-directive .transfer-column").count()
                            == 2
                        )
                        assert (
                            page.locator(
                                ".boost-backdrop img, .boost-candidates img"
                            ).count()
                            > 0
                        )
                        assert page.locator(".circuit-art").evaluate(
                            "e => !['rgb(255, 255, 255)', 'rgba(0, 0, 0, 0)'].includes(getComputedStyle(e).backgroundColor)"
                        )
                    if width <= 650:
                        assert (
                            page.locator(".masthead nav").evaluate(
                                "e => getComputedStyle(e).position"
                            )
                            == "fixed"
                        )
                    page.screenshot(
                        path=str(screenshots / f"mobile-final-{route}-{width}.png"),
                        full_page=True,
                    )
            page.evaluate("location.hash='strategy'")
            original_photo = page.locator(".race-photo").get_attribute("src")
            page.locator("[data-round='4']").click()
            assert page.locator(".race-photo").get_attribute("src") != original_photo
            # Changing rounds starts a new image request; wait for its actual
            # load rather than inspecting the freshly replaced <img> in-flight.
            page.wait_for_function(
                "document.querySelector('.race-photo')?.complete && document.querySelector('.race-photo').naturalWidth > 0",
                timeout=10000,
            )
            # Expired/failed automatic refresh cannot leave an old usable plan.
            expired = dict(
                updated,
                generated_at=(
                    datetime.now(timezone.utc) - timedelta(hours=7)
                ).isoformat(),
            )
            page.route("**/forecast.json*", lambda r: r.fulfill(json=expired))
            page.evaluate("document.dispatchEvent(new Event('visibilitychange'))")
            page.wait_for_function(
                "document.querySelector('#strategy')?.textContent.includes('six hours old')",
                timeout=15000,
            )
            assert page.locator("[data-round]").count() == 0
            assert not errors, errors
            assert not writes, writes
            print(
                json.dumps(
                    {
                        "automatic_solves": len(workers),
                        "chip_scroll_stable": True,
                        "project_path": url,
                        "widths": [1440, 768, 390, 320],
                        "automatic_publication_refresh": True,
                        "expired_data_blocked": True,
                        "page_errors": errors,
                        "account_submissions": 0,
                    }
                )
            )
            context.close()
        finally:
            browser.close()


if __name__ == "__main__":
    main()
