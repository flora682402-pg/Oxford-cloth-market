"""Real-browser tests (Chromium via Playwright) against a production build
served the way Cloudflare Pages serves it, security headers included.
Run: python3 -m pytest tests/test_browser.py
"""
from __future__ import annotations

import datetime as dt
import shutil

import pytest
from playwright.sync_api import expect, sync_playwright

import build
import serve

WIDTHS = [320, 390, 768, 1024, 1440]


@pytest.fixture(scope="module")
def base(tmp_path_factory):
    out = tmp_path_factory.mktemp("dist")
    shutil.rmtree(out)
    build.build(out=out, today=dt.date(2026, 11, 8))
    srv = serve.start(out)
    yield f"http://127.0.0.1:{srv.server_address[1]}"
    srv.shutdown()


@pytest.fixture(scope="module")
def browser():
    with sync_playwright() as p:
        b = p.chromium.launch()
        yield b
        b.close()


@pytest.fixture()
def open_page(browser, base):
    """Open a page; collects console errors (CSP violations included)."""
    contexts = []

    def _open(path, width=1440, height=900, now=None, **kw):
        ctx = browser.new_context(viewport={"width": width, "height": height}, **kw)
        contexts.append(ctx)
        # Fonts come from Google; block them so results don't depend on the network.
        ctx.route("**/*", lambda r: r.abort() if not r.request.url.startswith(base) else r.continue_())
        page = ctx.new_page()
        if now is not None:
            page.clock.set_fixed_time(now)
        page.errors = []
        # Ignore: blocked Google Fonts, and the 404 status of the not-found page itself.
        page.on("console", lambda m: page.errors.append(m.text)
                if m.type == "error" and "fonts.g" not in m.text and "ERR_FAILED" not in m.text
                and not (path.startswith("/does-not") and "404" in m.text) else None)
        page.on("pageerror", lambda e: page.errors.append(str(e)))
        page.response = page.goto(base + path, wait_until="load")
        return page

    yield _open
    for c in contexts:
        c.close()


@pytest.mark.parametrize("width", WIDTHS)
@pytest.mark.parametrize("path", ["/", "/clothing", "/does-not-exist"])
def test_no_overflow_and_no_errors(open_page, path, width):
    page = open_page(path, width=width)
    assert page.evaluate("document.documentElement.scrollWidth - document.documentElement.clientWidth") <= 0
    page.wait_for_timeout(200)
    assert page.errors == []


def test_security_headers_present(open_page):
    page = open_page("/")
    h = page.response.headers
    assert "frame-ancestors 'none'" in h["content-security-policy"]
    assert h["x-content-type-options"] == "nosniff"


def test_not_found_page(open_page):
    page = open_page("/no-such-page")
    assert page.response.status == 404
    assert page.locator("h1").inner_text() == "Page not found"


def test_html_extension_redirects_to_clean_url(open_page):
    page = open_page("/clothing.html")
    assert page.url.endswith("/clothing")


def test_all_images_load(open_page):
    for path in ["/", "/clothing"]:
        page = open_page(path)
        page.evaluate("window.scrollTo(0, document.body.scrollHeight)")
        page.wait_for_load_state("networkidle")
        page.evaluate("document.querySelectorAll('img').forEach(i => i.loading = 'eager')")
        page.wait_for_function("[...document.images].every(i => i.complete)")
        broken = page.evaluate("[...document.images].filter(i => !i.naturalWidth).map(i => i.src)")
        assert broken == []


def test_no_layout_shift_while_loading(open_page):
    page = open_page("/clothing", width=390, height=844)
    page.evaluate("window.scrollTo(0, 3000)")
    page.wait_for_timeout(800)
    cls = page.evaluate("""() => new Promise(r => {
        let s = 0; new PerformanceObserver(l => l.getEntries().forEach(e => { if (!e.hadRecentInput) s += e.value; }))
          .observe({type: 'layout-shift', buffered: true}); setTimeout(() => r(s), 300); })""")
    assert cls < 0.02


def test_phone_menu_open_escape_close(open_page):
    page = open_page("/", width=390, height=844)
    btn = page.locator("#menuBtn")
    btn.click()
    assert page.locator("#drawer").is_visible()
    assert btn.get_attribute("aria-expanded") == "true"
    assert "menu-open" in page.locator("#hdr").get_attribute("class")
    page.keyboard.press("Escape")
    assert page.locator("#drawer").is_hidden()
    assert page.evaluate("document.activeElement.id") == "menuBtn"


def test_phone_menu_link_closes_menu(open_page):
    page = open_page("/", width=390, height=844)
    page.locator("#menuBtn").click()
    page.locator("#drawer a", has_text="Pop-ups").click()
    assert page.locator("#drawer").is_hidden()


def test_menu_hidden_on_desktop(open_page):
    page = open_page("/", width=1440)
    assert page.locator("#menuBtn").is_hidden()
    assert page.locator(".nav").first.is_visible()


def test_badge_docks_on_scroll(open_page):
    page = open_page("/", width=1440)
    page.mouse.wheel(0, 600)
    page.wait_for_function("document.getElementById('hdr').classList.contains('scrolled')")
    page.wait_for_timeout(500)
    box = page.locator(".badge").bounding_box()
    assert 55 <= box["height"] <= 61  # 58px docked size, same as before


@pytest.mark.parametrize("hash_,count,title", [("", 22, "Clothing"), ("#ties", 6, "Ties"),
                                               ("#shirts", 9, "Shirts"), ("#accessories", 0, "Accessories"),
                                               ("#nonsense", 22, "Clothing")])
def test_clothing_filters(open_page, hash_, count, title):
    page = open_page("/clothing" + hash_)
    assert page.locator(".item:visible").count() == count
    assert page.locator("#shopTitle").inner_text() == title
    assert page.locator("#empty").is_visible() == (count == 0)


def test_filter_chip_click_updates_without_reload(open_page):
    page = open_page("/clothing")
    page.locator(".chips a[data-k=tailoring]").click()
    expect(page.locator(".item:visible")).to_have_count(3)
    expect(page.locator(".chips a[data-k=tailoring]")).to_have_attribute("aria-current", "true")


def test_newsletter_never_claims_success_without_provider(open_page):
    page = open_page("/")
    page.fill("#email", "not-an-email")
    page.locator("#nl button").click()
    assert "valid email" in page.locator("#nlMsg").inner_text()
    page.fill("#email", "michael@example.com")
    page.locator("#nl button").click()
    msg = page.locator("#nlMsg").inner_text()
    assert "opens soon" in msg and "on the list" not in msg


def test_skip_link_is_first_focus(open_page):
    page = open_page("/")
    page.keyboard.press("Tab")
    assert page.evaluate("document.activeElement.className") == "skip"
    assert page.locator(".skip").is_visible()


def test_anchor_targets_clear_sticky_header(open_page):
    page = open_page("/", width=1440)
    page.locator(".ftr a", has_text="Pop-ups").click()
    page.wait_for_timeout(600)
    header_bottom = page.locator("#hdr").bounding_box()["y"] + page.locator("#hdr").bounding_box()["height"]
    assert page.locator("#popups h2").bounding_box()["y"] > header_bottom


def test_footer_groups_stay_open_on_desktop(open_page):
    page = open_page("/", width=1440)
    page.locator(".ftr summary", has_text="Shop").click()
    assert page.locator(".ftr details").first.evaluate("d => d.open")


def test_footer_groups_collapse_on_phone(open_page):
    page = open_page("/", width=390, height=844)
    assert not page.locator(".ftr details").first.evaluate("d => d.open")
    page.locator(".ftr summary", has_text="Shop").click()
    assert page.locator(".ftr details").first.evaluate("d => d.open")


@pytest.mark.parametrize("now,visible", [(dt.datetime(2026, 11, 21, 20), 2),   # day of the first event
                                         (dt.datetime(2026, 11, 22, 9), 1),
                                         (dt.datetime(2026, 12, 14, 9), 0)])
def test_past_events_hidden_between_builds(open_page, now, visible):
    """The page was built on Nov 8; a visitor later must not see finished events."""
    page = open_page("/", now=now)
    assert page.locator(".events [data-date]:visible").count() == visible
    assert page.locator("#noEvents").is_visible() == (visible == 0)


def test_works_with_javascript_disabled(open_page):
    page = open_page("/clothing", java_script_enabled=False)
    assert page.locator(".item:visible").count() == 22  # everything listed, nothing hidden


def test_reduced_motion_respected(open_page):
    page = open_page("/", reduced_motion="reduce")
    assert page.locator(".badge").evaluate("e => getComputedStyle(e).transitionDuration") == "0s"
