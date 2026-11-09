"""Build, content and markup tests. Run: python3 -m pytest tests"""
from __future__ import annotations

import datetime as dt
import html.parser
import json
import re
import shutil
from pathlib import Path

import pytest
from PIL import Image

import build

TODAY = dt.date(2026, 11, 8)
VOID = {"area", "base", "br", "col", "embed", "hr", "img", "input", "link", "meta", "source", "track", "wbr"}


@pytest.fixture()
def site(tmp_path, monkeypatch):
    """A private copy of the project so tests can edit data safely."""
    root = tmp_path / "site"
    shutil.copytree(build.ROOT, root, ignore=shutil.ignore_patterns("dist", "preview", "__pycache__", ".pytest_cache", "reports", ".git"))
    monkeypatch.setattr(build, "ROOT", root)
    return root


@pytest.fixture(scope="module")
def dist(tmp_path_factory):
    """One shared production build for the read-only checks."""
    out = tmp_path_factory.mktemp("dist") / "out"
    return build.build(out=out, today=TODAY)


def edit_json(path: Path, fn):
    data = json.loads(path.read_text())
    fn(data)
    path.write_text(json.dumps(data))


class Doc(html.parser.HTMLParser):
    """Collects tags, attributes and structural errors from a page."""

    def __init__(self, text):
        super().__init__(convert_charrefs=True)
        self.stack, self.errors, self.ids, self.tags, self.text = [], [], [], [], []
        self.feed(text)
        self.close()
        if self.stack:
            self.errors.append(f"unclosed tags: {self.stack}")

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        self.tags.append((tag, a))
        if "id" in a:
            self.ids.append(a["id"])
        for k in a:
            if k.startswith("on"):
                self.errors.append(f"inline event handler {k} on <{tag}>")
        if tag not in VOID:
            self.stack.append(tag)

    def handle_startendtag(self, tag, attrs):
        self.handle_starttag(tag, attrs)
        if tag not in VOID:
            self.stack.pop()

    def handle_endtag(self, tag):
        if tag in VOID:
            return
        if not self.stack or self.stack[-1] != tag:
            self.errors.append(f"unexpected </{tag}> (open: {self.stack[-3:]})")
            if tag in self.stack:
                while self.stack and self.stack.pop() != tag:
                    pass
            return
        self.stack.pop()

    def handle_data(self, data):
        self.text.append(data)

    def all(self, tag):
        return [a for t, a in self.tags if t == tag]


PAGES = ["index.html", "clothing.html", "404.html"]


def load(dist, name):
    return Doc((dist / name).read_text())


# ------------------------------------------------------------ structure

@pytest.mark.parametrize("name", PAGES)
def test_markup_is_well_formed(dist, name):
    doc = load(dist, name)
    assert doc.errors == []
    assert (dist / name).read_text().startswith("<!doctype html>")
    assert doc.all("html")[0].get("lang") == "en"


@pytest.mark.parametrize("name", PAGES)
def test_ids_unique_and_one_h1(dist, name):
    doc = load(dist, name)
    assert len(doc.ids) == len(set(doc.ids)), [i for i in doc.ids if doc.ids.count(i) > 1]
    assert len(doc.all("h1")) == 1


@pytest.mark.parametrize("name", PAGES)
def test_images_have_alt_and_dimensions(dist, name):
    for img in load(dist, name).all("img"):
        assert "alt" in img, img
        assert img.get("width", "").isdigit() and img.get("height", "").isdigit(), img


@pytest.mark.parametrize("name", PAGES)
def test_csp_compatible_no_inline_code(dist, name):
    text = (dist / name).read_text()
    for m in re.finditer(r"<script([^>]*)>(.*?)</script>", text, re.S):
        attrs, body = m.groups()
        assert "src=" in attrs or 'type="application/ld+json"' in attrs, attrs
    assert "<style" not in text
    assert load(dist, name).errors == []  # includes the inline-handler check


def local_target(dist: Path, url: str) -> Path | None:
    path = url.split("#", 1)[0].split("?", 1)[0]
    if not path or path.startswith(("http:", "https:", "mailto:")):
        return None
    if path == "/":
        return dist / "index.html"
    candidate = dist / path.lstrip("/")
    return candidate if candidate.suffix else candidate.with_suffix(".html")


@pytest.mark.parametrize("name", PAGES)
def test_every_local_link_and_asset_exists(dist, name):
    doc = load(dist, name)
    refs = [a["href"] for a in doc.all("a")] + [l["href"] for l in doc.all("link")] + \
           [s["src"] for s in doc.all("script") if "src" in s] + [i["src"] for i in doc.all("img")]
    for img in doc.all("img") + doc.all("source"):
        refs += [part.strip().split(" ")[0] for part in img.get("srcset", "").split(",") if part.strip()]
    missing = [r for r in refs if (t := local_target(dist, r)) is not None and not t.is_file()]
    assert missing == []


@pytest.mark.parametrize("name", PAGES)
def test_same_page_anchors_resolve(dist, name):
    doc = load(dist, name)
    filters = {a["data-k"] for a in doc.all("a") if "data-k" in a}
    bad = [a["href"] for a in doc.all("a") if a["href"].startswith("#")
           and a["href"][1:] not in doc.ids and a["href"][1:] not in filters and a["href"] != "#top"]
    assert bad == []


def test_cross_page_anchors_resolve(dist):
    index_ids = set(load(dist, "index.html").ids)
    clothing = load(dist, "clothing.html")
    filters = {a["data-k"] for a in clothing.all("a") if "data-k" in a}
    for name in PAGES:
        for a in load(dist, name).all("a"):
            href = a["href"]
            if href.startswith("/#"):
                assert href[2:] in index_ids, (name, href)
            if href.startswith("/clothing#"):
                assert href.split("#")[1] in filters, (name, href)


def test_no_dead_read_more_links(dist):
    """Editorial 'Read more' only renders when an article URL exists."""
    assert [a for a in load(dist, "index.html").all("a") if a["href"] in ("#", "", "#editorial") and a.get("class") == "ulink"] == []
    assert "Read more" not in (dist / "index.html").read_text()


def test_read_more_appears_when_article_has_url(site):
    edit_json(site / "data/editorial.json", lambda d: d["articles"][0].__setitem__("url", "https://oxfordclothmarket.com/journal/brooks"))
    text = (build.build(today=TODAY) / "index.html").read_text()
    assert text.count("Read more") == 1 and 'href="https://oxfordclothmarket.com/journal/brooks"' in text


# ------------------------------------------------------------------ SEO

@pytest.mark.parametrize("name,path", [("index.html", "/"), ("clothing.html", "/clothing")])
def test_seo_metadata(dist, name, path):
    doc = load(dist, name)
    metas = {m.get("name") or m.get("property"): m.get("content") for m in doc.all("meta")}
    assert 50 <= len(metas["description"]) <= 170
    assert metas["og:image"].startswith("https://") and metas["og:image"].endswith("og.jpg")
    canon = [l["href"] for l in doc.all("link") if l.get("rel") == "canonical"]
    assert canon == ["https://oxfordclothmarket.com" + path]
    title = [t for t, a in doc.tags if t == "title"]
    assert title


@pytest.mark.parametrize("name", ["index.html", "clothing.html"])
def test_structured_data_is_valid_json(dist, name):
    blocks = re.findall(r'<script type="application/ld\+json">(.*?)</script>', (dist / name).read_text(), re.S)
    assert len(blocks) == 1
    data = json.loads(blocks[0])
    assert data["@context"] == "https://schema.org" and data["@graph"]


def test_404_is_noindex(dist):
    metas = {m.get("name"): m.get("content") for m in load(dist, "404.html").all("meta")}
    assert metas["robots"] == "noindex"


def test_robots_sitemap_headers(dist):
    assert "Sitemap: https://oxfordclothmarket.com/sitemap.xml" in (dist / "robots.txt").read_text()
    sm = (dist / "sitemap.xml").read_text()
    assert sm.count("<loc>") == 2 and "/clothing</loc>" in sm
    h = (dist / "_headers").read_text()
    for needle in ("Content-Security-Policy", "frame-ancestors 'none'", "Strict-Transport-Security",
                   "X-Content-Type-Options: nosniff", "immutable"):
        assert needle in h


def test_icons_and_manifest(dist):
    for f in ("favicon.ico", "favicon-32.png", "apple-touch-icon.png", "icon-512.png"):
        assert (dist / f).is_file()
    with Image.open(dist / "apple-touch-icon.png") as im:
        assert im.size == (180, 180)
    assert json.loads((dist / "site.webmanifest").read_text())["icons"]


# ----------------------------------------------------------- performance

def test_assets_are_fingerprinted(dist):
    css = list((dist / "assets").glob("styles.*.css"))
    js = list((dist / "assets").glob("site.*.js"))
    assert len(css) == len(js) == 1
    assert re.fullmatch(r"styles\.[0-9a-f]{10}\.css", css[0].name)
    assert f"/assets/{css[0].name}" in (dist / "index.html").read_text()


def test_product_images_have_phone_sizes(dist):
    small = list((dist / "img/p").glob("*-400.webp"))
    assert len(small) == 22
    for f in small:
        with Image.open(f) as im:
            assert im.width <= 400
    assert sum(f.stat().st_size for f in small) < sum(f.stat().st_size for f in (dist / "img/p").glob("*-600.webp"))


def test_hero_is_prioritised_and_others_lazy(dist):
    imgs = load(dist, "index.html").all("img")
    hero = next(i for i in imgs if "/img/hero-" in i["src"])
    assert hero.get("fetchpriority") == "high" and "loading" not in hero
    lazy = [i for i in imgs if i.get("loading") == "lazy"]
    assert len(lazy) >= len(imgs) - 2  # only the logo and hero load eagerly
    rack = load(dist, "clothing.html").all("img")
    products = [i for i in rack if "/img/p/" in i["src"]]
    assert "loading" not in products[0] and products[0].get("fetchpriority") == "high"
    assert all(i.get("loading") == "lazy" for i in products[4:])


def test_page_weight_budget(dist):
    for name in PAGES:
        assert (dist / name).stat().st_size < 60_000, name
    assert next((dist / "assets").glob("*.css")).stat().st_size < 30_000
    assert next((dist / "assets").glob("*.js")).stat().st_size < 12_000


# ------------------------------------------------------------- content

def test_visible_copy_preserved(dist):
    text = (dist / "index.html").read_text()
    for phrase in ["Great style doesn't follow trends.<br>It lasts.", "Product in Focus", "Find us in person",
                   "Sport coats with real shoulders", "Your home for vintage and secondhand style",
                   "Offline Tulsa Collective", "Sat · Nov", "Sun · Dec", "Shop the rack"]:
        assert phrase in text, phrase


def test_clothing_lists_every_product(dist):
    doc = load(dist, "clothing.html")
    items = [a for a in doc.all("a") if a.get("class") == "item"]
    assert len(items) == 22
    assert all(a["href"].startswith("https://www.ebay.com/itm/") for a in items)
    counts = {a["data-k"]: a for a in doc.all("a") if "data-k" in a}
    assert set(counts) == {"all", "shirts", "tailoring", "trousers", "ties", "accessories"}


def test_featured_cards_in_order(dist):
    text = (dist / "index.html").read_text()
    ids = re.findall(r'class="card" href="https://www\.ebay\.com/itm/(\d+)"', text)
    assert ids == ["317189767758", "317189695687", "317189876211", "317190044523"]


# ------------------------------------------------------------ data safety

def test_product_text_is_escaped(site):
    def evil(d):
        d["items"][0]["name"] = 'Tie <script>alert(1)</script> & "quotes"'
        d["items"][0]["detail"] = "<img src=x onerror=alert(1)>"
    edit_json(site / "data/products.json", evil)
    out = build.build(today=TODAY)
    text = (out / "clothing.html").read_text()
    assert "<script>alert(1)" not in text and "<img src=x" not in text
    assert "Tie &lt;script&gt;alert(1)&lt;/script&gt; &amp; &#34;quotes&#34;" in text
    assert Doc(text).errors == []


def test_json_ld_cannot_close_script():
    assert "</script>" not in build.json_ld({"name": "</script><script>alert(1)</script>"})
    assert json.loads(build.json_ld({"name": "</script>"}))["name"] == "</script>"


@pytest.mark.parametrize("field,value,message", [
    ("price", "25", "price"),
    ("price", "$25.00", "price"),
    ("category", "hats", "unknown category"),
    ("url", "http://www.ebay.com/itm/1", "https"),
    ("url", "https://evil.example/itm/1", "ebay.com"),
    ("image", "../../config.json", "image"),
    ("id", "abc", "digits"),
    ("name", "", "missing name"),
])
def test_invalid_product_data_is_rejected(site, field, value, message):
    edit_json(site / "data/products.json", lambda d: d["items"][0].__setitem__(field, value))
    with pytest.raises(build.BuildError, match=message):
        build.build(today=TODAY)


def test_duplicate_product_ids_rejected(site):
    edit_json(site / "data/products.json", lambda d: d["items"].append(dict(d["items"][0])))
    with pytest.raises(build.BuildError, match="duplicate"):
        build.build(today=TODAY)


def test_bad_event_date_rejected(site):
    edit_json(site / "data/events.json", lambda d: d["events"][0].__setitem__("date", "Nov 21"))
    with pytest.raises(build.BuildError, match="YYYY-MM-DD"):
        build.build(today=TODAY)


def test_failed_build_leaves_previous_output(site):
    good = build.build(today=TODAY)
    edit_json(site / "data/products.json", lambda d: d["items"][0].__setitem__("price", "free"))
    with pytest.raises(build.BuildError):
        build.build(today=TODAY)
    assert (good / "index.html").is_file()


# ---------------------------------------------------------------- events

def test_past_events_dropped_at_build(site):
    out = build.build(today=dt.date(2026, 11, 22))
    text = (out / "index.html").read_text()
    assert "Offline Tulsa Collective" not in text and "Tulsa Indie Market" in text
    assert 'id="noEvents" hidden' in text


def test_empty_event_list_shows_message(site):
    out = build.build(today=dt.date(2026, 12, 14))
    text = (out / "index.html").read_text()
    assert 'id="noEvents">' in text and "<li data-date" not in text


def test_event_weekday_labels_match_dates(dist):
    text = (dist / "index.html").read_text()
    for date, label in re.findall(r'data-date="([\d-]+)"><div class="date"><span class="label">([^<]+)</span>', text):
        assert dt.date.fromisoformat(date).strftime("%a · %b") == label


# ------------------------------------------------------------ newsletter

def test_newsletter_without_provider_has_no_action(dist):
    form = load(dist, "index.html").all("form")[0]
    assert "action" not in form and "novalidate" in form
    assert "form-action 'self';" in (dist / "_headers").read_text()


def test_newsletter_with_provider_posts_and_csp_allows_it(site):
    edit_json(site / "config.json", lambda c: c.__setitem__("newsletter_action", "https://buttondown.com/api/emails/embed-subscribe/ocm"))
    out = build.build(today=TODAY)
    form = load(out, "index.html").all("form")[0]
    assert form["action"].startswith("https://buttondown.com/") and form["method"] == "post"
    assert "form-action 'self' https://buttondown.com" in (out / "_headers").read_text()


# --------------------------------------------------------------- preview

def test_preview_build_uses_relative_links(site):
    out = build.build(preview=True, today=TODAY)
    idx = (out / "index.html").read_text()
    assert not idx.startswith("<!doctype") and "<title>" in idx
    assert 'href="clothing.html#shirts"' in idx and 'href="/' not in idx
    assert not (out / "_headers").exists()
    # Supporting pages are served as written, so they must be complete documents.
    clo = (out / "clothing.html").read_text()
    assert clo.startswith("<!doctype html>") and Doc(clo).errors == []
    assert 'href="index.html"' in clo and 'href="/' not in clo


def test_product_in_focus_background_shows_the_jacket_not_the_face(dist):
    """The focus background sits behind product cards; cropping it near the top puts a face behind them."""
    text = (dist / "index.html").read_text()
    m = re.search(r'focus-teal-\d+\.webp"[^>]*object-position:center (\d+)%', text)
    assert m and 45 <= int(m.group(1)) <= 60, m and m.group(0)


# ------------------------------------------------------------ templates

def test_homepage_tiles_come_from_data(site):
    def edit(d):
        d["rows"][0][0]["copy"] = "Brand-new tailoring copy & more"
        d["rows"][0][0]["link"] = "Shop jackets"
    edit_json(site / "data/home.json", edit)
    text = (build.build(today=TODAY) / "index.html").read_text()
    assert "Brand-new tailoring copy &amp; more" in text and ">Shop jackets</a>" in text
    assert text.count('class="tile"') == 4


@pytest.mark.parametrize("change,message", [
    (lambda d: d["rows"][0][0].__setitem__("category", "hats"), "unknown category"),
    (lambda d: d["rows"][0][0].__setitem__("image", "missing.webp"), "not found"),
    (lambda d: d["rows"][0][0].__setitem__("position", "top; color: red"), "position"),
    (lambda d: d["rows"][0].pop(), "exactly two tiles"),
    (lambda d: d["focus"].__setitem__("alt", ""), "missing alt"),
])
def test_invalid_home_data_is_rejected(site, change, message):
    edit_json(site / "data/home.json", change)
    with pytest.raises(build.BuildError, match=message):
        build.build(today=TODAY)


def test_template_typos_fail_the_build(site):
    """StrictUndefined: a misspelled variable must stop the build, not render blank."""
    p = site / "templates/404.html"
    p.write_text(p.read_text().replace("{{ page('clothing') }}", "{{ pgae('clothing') }}"))
    with pytest.raises(Exception, match="pgae"):
        build.build(today=TODAY)


def test_no_html_left_in_build_py():
    src = (build.ROOT / "build.py").read_text()
    assert not re.search(r"<(div|section|main|footer|header|nav|ul|li|h[1-6]|p)[ >]", src)


# ---------------------------------------------------------- lifestyle photos

def test_lifestyle_photos_have_responsive_sizes(dist):
    """Every lifestyle photo offers several widths so phones download small files."""
    doc = load(dist, "index.html")
    photos = [i for i in doc.all("img") if re.search(r"/img/[a-z-]+-\d+\.webp$", i["src"])]
    assert len(photos) >= 9
    for img in photos:
        widths = [int(w) for w in re.findall(r"(\d+)w", img["srcset"])]
        assert len(widths) >= 3 and min(widths) == 640, img["src"]
        assert img.get("sizes"), img["src"]
    phone = [s for s in doc.all("source") if "hero-phone" in s.get("srcset", "")]
    assert phone and phone[0]["sizes"] == "100vw"


def test_photo_copies_are_never_upscaled(dist):
    for src in (build.ROOT / "media/mood").iterdir():
        with Image.open(src) as im:
            natural = im.width
        for out in (dist / "img").glob(f"{src.stem}-*.webp"):
            if not re.fullmatch(rf"{re.escape(src.stem)}-\d+\.webp", out.name):
                continue
            with Image.open(out) as im:
                assert im.width <= natural, out.name


def test_social_preview_image_is_1200_wide(dist):
    with Image.open(dist / "img/og.jpg") as im:
        assert im.width == 1200
