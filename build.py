#!/usr/bin/env python3
"""Build the Oxford Cloth Market website.

    python3 build.py              # production site  -> dist/
    python3 build.py --preview    # Claude preview    -> preview/

Inputs: config.json, data/*.json, src/ (CSS + JS), media/ (images).
Only needs Python 3.9+ and Pillow. Every piece of data is validated and
HTML-escaped before it reaches a page, so a later automatic eBay sync can
write data/products.json without being able to break the markup.
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import html
import json
import re
import shutil
import sys
from pathlib import Path
from urllib.parse import urlparse

from PIL import Image

ROOT = Path(__file__).resolve().parent
PRODUCT_WIDTHS = (400, 600)  # 600 is the source size; 400 serves phones
CATEGORY_RE = re.compile(r"^[a-z][a-z-]*$")
PRICE_RE = re.compile(r"^\d{1,6}\.\d{2}$")
DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
ID_RE = re.compile(r"^\d{6,20}$")


class BuildError(Exception):
    """Raised for invalid content; the message names the bad field."""


def esc(value) -> str:
    """Escape text or attribute values for HTML."""
    return html.escape(str(value), quote=True)


def json_ld(data) -> str:
    """Serialise structured data safely for an inline <script> block."""
    text = json.dumps(data, ensure_ascii=False, separators=(",", ":"))
    return text.replace("<", "\\u003c").replace(">", "\\u003e").replace("&", "\\u0026")


def https_url(value: str, field: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme != "https" or not parsed.netloc:
        raise BuildError(f"{field}: expected an https:// URL, got {value!r}")
    return value


# ---------------------------------------------------------------- validation

def load_json(path: Path):
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise BuildError(f"{path.name}: {exc}") from exc


def validate_config(cfg: dict) -> dict:
    for key in ("site_url", "name", "tagline", "description", "instagram", "ebay_store", "categories"):
        if not cfg.get(key):
            raise BuildError(f"config.json: missing {key}")
    https_url(cfg["site_url"], "config.site_url")
    cfg["site_url"] = cfg["site_url"].rstrip("/")
    https_url(cfg["instagram"], "config.instagram")
    https_url(cfg["ebay_store"], "config.ebay_store")
    if cfg.get("newsletter_action"):
        https_url(cfg["newsletter_action"], "config.newsletter_action")
    for key, label in cfg["categories"]:
        if not CATEGORY_RE.match(key) or not label:
            raise BuildError(f"config.categories: bad entry {key!r}")
    return cfg


def validate_products(data: dict, categories: set[str], media: Path) -> list[dict]:
    items = data.get("items")
    if not isinstance(items, list):
        raise BuildError("products.json: 'items' must be a list")
    if not DATE_RE.match(str(data.get("updated", ""))):
        raise BuildError("products.json: 'updated' must be YYYY-MM-DD")
    seen = set()
    for n, it in enumerate(items):
        where = f"products.json item {n} ({it.get('id', '?')})"
        for key in ("id", "category", "name", "detail", "price", "url", "image", "brand"):
            if not isinstance(it.get(key), str) or not it[key].strip():
                raise BuildError(f"{where}: missing {key}")
        if not ID_RE.match(it["id"]):
            raise BuildError(f"{where}: id must be digits")
        if it["id"] in seen:
            raise BuildError(f"{where}: duplicate id")
        seen.add(it["id"])
        if it["category"] not in categories:
            raise BuildError(f"{where}: unknown category {it['category']!r}")
        if not PRICE_RE.match(it["price"]):
            raise BuildError(f"{where}: price must look like 25.00")
        https_url(it["url"], f"{where}.url")
        if not urlparse(it["url"]).netloc.endswith("ebay.com"):
            raise BuildError(f"{where}: url must be an ebay.com listing")
        if "/" in it["image"] or not (media / it["image"]).is_file():
            raise BuildError(f"{where}: image {it['image']!r} not found in media/products")
        if it.get("currency", "USD") != "USD":
            raise BuildError(f"{where}: only USD prices are supported")
    featured = [it for it in items if it.get("featured")]
    if len({it["featured"]["order"] for it in featured}) != len(featured):
        raise BuildError("products.json: two featured items share an order number")
    return items


def validate_events(data: dict) -> list[dict]:
    events = data.get("events", [])
    for n, ev in enumerate(events):
        for key in ("date", "name", "where", "url"):
            if not ev.get(key):
                raise BuildError(f"events.json event {n}: missing {key}")
        if not DATE_RE.match(ev["date"]):
            raise BuildError(f"events.json event {n}: date must be YYYY-MM-DD")
        dt.date.fromisoformat(ev["date"])
        https_url(ev["url"], f"events.json event {n}.url")
    return sorted(events, key=lambda e: e["date"])


def validate_articles(data: dict, media: Path) -> list[dict]:
    arts = data.get("articles", [])
    for n, a in enumerate(arts):
        for key in ("title", "dek", "image", "alt"):
            if not a.get(key):
                raise BuildError(f"editorial.json article {n}: missing {key}")
        if not (media / a["image"]).is_file():
            raise BuildError(f"editorial.json article {n}: image {a['image']!r} not found")
        if a.get("url"):
            https_url(a["url"], f"editorial.json article {n}.url")
    return arts


# ------------------------------------------------------------------ assets

_VARIANT_CACHE: dict[tuple, bytes] = {}


def _encode_variant(src: Path, mtime: int, width: int) -> bytes:
    """Resize/encode one product image width (memoised within a process)."""
    key = (str(src), mtime, width)
    if key not in _VARIANT_CACHE:
        import io
        with Image.open(src) as im:
            if im.width <= width and im.format == "WEBP":
                _VARIANT_CACHE[key] = src.read_bytes()  # already right-sized: never re-compress
                return _VARIANT_CACHE[key]
            buf = io.BytesIO()
            im = im.convert("RGB")
            if im.width > width:
                im = im.resize((width, round(im.height * width / im.width)), Image.LANCZOS)
            im.save(buf, "WEBP", quality=80, method=6)
        _VARIANT_CACHE[key] = buf.getvalue()
    return _VARIANT_CACHE[key]

class Assets:
    """Copies/creates every static file and remembers image dimensions."""

    def __init__(self, out: Path, prefix: str):
        self.out, self.prefix, self.dims = out, prefix, {}

    def url(self, rel: str) -> str:
        return self.prefix + rel

    def _record(self, rel: str, path: Path):
        with Image.open(path) as im:
            self.dims[rel] = im.size

    def copy(self, src: Path, rel: str) -> str:
        dest = self.out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(src, dest)
        self._record(rel, dest)
        return rel

    def fingerprint(self, src: Path, folder: str = "assets") -> str:
        data = src.read_bytes()
        digest = hashlib.sha256(data).hexdigest()[:10]
        rel = f"{folder}/{src.stem}.{digest}{src.suffix}"
        dest = self.out / rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        dest.write_bytes(data)
        return rel

    def product_variants(self, src: Path, pid: str) -> dict[int, str]:
        out = {}
        for w in PRODUCT_WIDTHS:
            rel = f"img/p/{pid}-{w}.webp"
            dest = self.out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_encode_variant(src, src.stat().st_mtime_ns, w))
            self._record(rel, dest)
            out[w] = rel
        return out

    def icons(self, logo: Path):
        with Image.open(logo) as im:
            im = im.convert("RGBA")
            for size, name in ((32, "favicon-32.png"), (180, "apple-touch-icon.png"), (512, "icon-512.png")):
                canvas = Image.new("RGBA", (size, size), (242, 234, 219, 255) if name != "favicon-32.png" else (0, 0, 0, 0))
                canvas.alpha_composite(im.resize((size, size), Image.LANCZOS))
                canvas.save(self.out / name, "PNG", optimize=True)
            im.resize((48, 48), Image.LANCZOS).save(self.out / "favicon.ico", sizes=[(16, 16), (32, 32), (48, 48)])

    def social_image(self, src: Path) -> str:
        rel = "img/og.jpg"
        with Image.open(src) as im:
            im.convert("RGB").save(self.out / rel, "JPEG", quality=84, optimize=True, progressive=True)
        self._record(rel, self.out / rel)
        return rel


# ----------------------------------------------------------------- markup

class Site:
    def __init__(self, cfg, products, events, articles, assets: Assets, preview: bool, today: dt.date):
        self.cfg, self.products, self.articles = cfg, products, articles
        self.assets, self.preview, self.today = assets, preview, today
        self.events = [e for e in events if dt.date.fromisoformat(e["date"]) >= today]
        self.cats = cfg["categories"]

    # Links differ between the real site (clean URLs) and the preview (files).
    def page(self, name: str) -> str:
        if self.preview:
            return {"index": "index.html", "clothing": "clothing.html"}[name]
        return {"index": "/", "clothing": "/clothing"}[name]

    def abs(self, path: str) -> str:
        return self.cfg["site_url"] + ("" if path.startswith("/") else "/") + path

    def img(self, rel: str, alt: str, *, cls="", style="", lazy=True, priority=False, srcset="", sizes="") -> str:
        w, h = self.assets.dims[rel]
        attrs = [f'src="{esc(self.assets.url(rel))}"']
        if srcset:
            attrs.append(f'srcset="{esc(srcset)}" sizes="{esc(sizes)}"')
        attrs.append(f'alt="{esc(alt)}" width="{w}" height="{h}"')
        if cls:
            attrs.append(f'class="{cls}"')
        if style:
            attrs.append(f'style="{esc(style)}"')
        attrs.append('loading="lazy" decoding="async"' if lazy else 'decoding="async"')
        if priority:
            attrs.append('fetchpriority="high"')
        return f"<img {' '.join(attrs)}>"

    def product_srcset(self, p: dict) -> str:
        return ", ".join(f"{self.assets.url(rel)} {w}w" for w, rel in p["variants"].items())

    @staticmethod
    def money(price: str) -> str:
        return "$" + (price[:-3] if price.endswith(".00") else price)

    # --- shared chrome
    def head(self, *, title, description, path, ld=None, noindex=False) -> str:
        c, a = self.cfg, self.assets
        og = a.url(a.og) if self.preview else self.abs(a.og)
        ow, oh = a.dims[a.og]
        lines = [
            '<meta charset="utf-8">',
            '<meta name="viewport" content="width=device-width, initial-scale=1, viewport-fit=cover">',
            f"<title>{esc(title)}</title>",
            f'<meta name="description" content="{esc(description)}">',
        ]
        if noindex:
            lines.append('<meta name="robots" content="noindex">')
        else:
            lines.append(f'<link rel="canonical" href="{esc(self.abs(path))}">')
        lines += [
            '<meta property="og:type" content="website">',
            f'<meta property="og:site_name" content="{esc(c["name"])}">',
            f'<meta property="og:title" content="{esc(title)}">',
            f'<meta property="og:description" content="{esc(description)}">',
            f'<meta property="og:url" content="{esc(self.abs(path))}">',
            f'<meta property="og:image" content="{esc(og)}">',
            f'<meta property="og:image:width" content="{ow}"><meta property="og:image:height" content="{oh}">',
            '<meta property="og:image:alt" content="Man in a brown sport coat and foulard tie by a window">',
            '<meta name="twitter:card" content="summary_large_image">',
            '<meta name="theme-color" content="#F2EADB">',
            f'<link rel="icon" href="{a.url("favicon.ico")}" sizes="48x48">',
            f'<link rel="icon" type="image/png" href="{a.url("favicon-32.png")}" sizes="32x32">',
            f'<link rel="apple-touch-icon" href="{a.url("apple-touch-icon.png")}">',
            f'<link rel="manifest" href="{a.url("site.webmanifest")}">',
            '<link rel="preconnect" href="https://fonts.googleapis.com">',
            '<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>',
            '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Caslon+Text:ital,wght@0,400;0,700;1,400&amp;family=Jost:wght@400;500&amp;display=swap">',
            f'<link rel="stylesheet" href="{a.url(a.css)}">',
            f'<script src="{a.url(a.js)}" defer></script>',
        ]
        if ld:
            lines.append(f'<script type="application/ld+json">{json_ld(ld)}</script>')
        return "\n".join(lines)

    def header(self, here: str) -> str:
        home = "" if here == "index" else self.page("index")
        clo = self.page("clothing")
        left = [("New In", clo), ("Clothing", clo), ("Shirts", clo + "#shirts"), ("Trousers", clo + "#trousers")]
        right = [("Tailoring", clo + "#tailoring"), ("Ties", clo + "#ties"), ("Accessories", clo + "#accessories"),
                 ("Editorial", home + "#editorial")]
        lis = lambda links: "\n".join(f'      <li><a href="{esc(h)}">{t}</a></li>' for t, h in links)
        drawer = "\n".join(f'      <li><a href="{esc(h)}">{t}</a></li>' for t, h in left + right + [("Pop-ups", home + "#popups")])
        badge_href = "#main" if here == "index" else self.page("index")
        logo = self.img("img/logo.webp", f"{self.cfg['name']}, est. {self.cfg['founded']}", lazy=False)
        return f"""<a class="skip" href="#main">Skip to content</a>
<header class="hdr" id="hdr">
  <nav class="hdr-in" aria-label="Main">
    <ul class="nav">
{lis(left)}
    </ul>
    <button class="iconbtn m-only" id="menuBtn" type="button" aria-label="Open menu" aria-expanded="false" aria-controls="drawer">
      <svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M3 7h18M3 12h18M3 17h18"/></svg>
    </button>
    <span></span>
    <ul class="nav r">
{lis(right)}
    </ul>
    <div class="right m-only">
      <a class="iconbtn" href="{esc(self.cfg['instagram'])}" aria-label="Instagram"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><rect x="3.5" y="3.5" width="17" height="17" rx="5"/><circle cx="12" cy="12" r="4"/><circle cx="17.2" cy="6.8" r=".8" fill="currentColor"/></svg></a>
      <a class="iconbtn" href="{esc(self.cfg['ebay_store'])}" aria-label="Shop on eBay"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="1.4" aria-hidden="true"><path d="M5 8h14l-1 12H6L5 8z"/><path d="M9 8V6a3 3 0 0 1 6 0v2"/></svg></a>
    </div>
    <a class="badge" href="{esc(badge_href)}" aria-label="{esc(self.cfg['name'])} home">{logo}</a>
  </nav>
  <nav class="drawer" id="drawer" hidden aria-label="Menu">
    <ul>
{drawer}
    </ul>
  </nav>
</header>"""

    def footer(self, here: str) -> str:
        home = "" if here == "index" else self.page("index")
        clo = self.page("clothing")
        action = self.cfg.get("newsletter_action")
        # With a provider the browser validates and posts natively (works without JS);
        # without one, site.js validates and explains that sign-up isn't open yet.
        form_attrs = f'action="{esc(action)}" method="post"' if action else "novalidate"
        shop = "".join(f'<li><a href="{esc(clo)}#{k}">{esc(l)}</a></li>' for k, l in self.cats if k != "accessories")
        logo = self.img("img/logo.webp", "")
        return f"""<footer class="ftr">
  <div class="ftr-in">
    <div class="ftr-top">
      <div>
        <h2>Sign up for new arrivals</h2>
        <form class="nl" id="nl" {form_attrs}>
          <label for="email" class="sr-only">Email address</label>
          <input id="email" name="email" type="email" placeholder="Email address" autocomplete="email" required>
          <button type="submit" aria-label="Sign up">→</button>
        </form>
        <p class="nl-msg" id="nlMsg" aria-live="polite"></p>
      </div>
      <details open><summary>Shop</summary><ul>{shop}</ul></details>
      <details open><summary>About</summary><ul><li><a href="{home}#about">Our story</a></li><li><a href="{home}#popups">Pop-ups</a></li><li><a href="{home}#editorial">Editorial</a></li></ul></details>
      <details open><summary>Follow</summary><ul><li><a href="{esc(self.cfg['instagram'])}">Instagram</a></li><li><a href="{esc(self.cfg['ebay_store'])}">eBay</a></li></ul></details>
    </div>
    <div class="sign">
      <p>{esc(self.cfg['tagline'])}</p>
      {logo}
    </div>
    <div class="legal"><span>© {self.today.year} {esc(self.cfg['name'])} · Est. {esc(self.cfg['founded'])}</span><a href="#top">Back to top</a></div>
  </div>
</footer>"""

    def document(self, head: str, body: str, fragment: bool = False) -> str:
        # Only the preview's main page is a fragment: the preview host wraps
        # that one page in <html>/<head>/<body>. Every other page is complete.
        if fragment:
            return head + "\n" + body + "\n"
        return f'<!doctype html>\n<html lang="en">\n<head>\n{head}\n</head>\n<body>\n{body}\n</body>\n</html>\n'

    # --- pages
    def index(self) -> str:
        c, clo = self.cfg, self.page("clothing")
        hero_phone = self.assets.dims["img/hero-phone.webp"]
        hero = (f'<picture><source media="(max-width:900px)" srcset="{self.assets.url("img/hero-phone.webp")}" '
                f'width="{hero_phone[0]}" height="{hero_phone[1]}">'
                + self.img("img/hero.webp", "Man in a brown sport coat and foulard tie holding a coffee by a window",
                           lazy=False, priority=True) + "</picture>")
        ph = lambda rel, alt, pos: f'<div class="ph">{self.img(rel, alt, style=f"object-position:{pos}")}</div>'

        def article(a, flip, anchor):
            link = f'\n      <a class="ulink" href="{esc(a["url"])}">Read more</a>' if a.get("url") else ""
            return f"""<section class="feature{' flip' if flip else ''}"{' id="editorial"' if anchor else ''}>
    <div class="txt">
      <p class="label kicker">Editorial</p>
      <h2>{esc(a['title'])}</h2>
      <p>{esc(a['dek'])}</p>{link}
    </div>
    <div class="img">{ph('img/' + a['image'], a['alt'], a.get('position', 'center 25%'))}</div>
  </section>"""

        arts = self.articles + [None, None]
        featured = sorted((p for p in self.products if p.get("featured")), key=lambda p: p["featured"]["order"])[:4]
        cards = "\n".join(f"""        <a class="card" href="{esc(p['url'])}">
          <div class="shot">{self.img(p['variants'][600], p['featured']['alt'] or p['name'], srcset=self.product_srcset(p), sizes='(max-width:900px) 50vw, 25vw')}</div>
          <h3>{esc(p['featured']['name'])}</h3><div class="meta"><span>{esc(p['featured']['detail'])}</span><span>{self.money(p['price'])}</span></div></a>"""
                          for p in featured)
        events = "\n".join(
            f"""        <li data-date="{e['date']}"><div class="date"><span class="label">{dt.date.fromisoformat(e['date']).strftime('%a · %b')}</span><b>{dt.date.fromisoformat(e['date']).day}</b></div><div><h3>{esc(e['name'])}</h3><span class="where">{esc(e['where'])}</span></div><a class="ulink" href="{esc(e['url'])}">Details</a></li>"""
            for e in self.events)
        none_hidden = " hidden" if self.events else ""
        body = f"""{self.header('index')}

<main id="main">
  <section class="hero">
    <div class="ph">{hero}</div>
    <div class="hero-cap">
      <h1>Great style doesn't follow trends.<br>It lasts.</h1>
      <div class="links"><a class="ulink" href="#about">Our story</a><a class="ulink" href="{clo}">Shop new in</a></div>
    </div>
  </section>

  <section class="duo">
    <div class="tile">{ph('img/tailoring.webp', 'Man in a corduroy sport coat, white shirt and patterned tie', 'center 12%')}
      <div class="copy"><p>Sport coats with real shoulders, honest tweed and herringbone, and the occasional made-in-Italy find. Vintage tailoring built to outlast the season it was bought in.</p><a class="ulink" href="{clo}#tailoring">Shop tailoring</a></div></div>
    <div class="tile">{ph('img/ties.webp', 'Man in a corduroy jacket with a paisley silk tie and pale trousers', 'center 6%')}
      <div class="copy"><p>Made-in-USA silk from Brooks Brothers, Burberrys and Gant. Repp stripes, foulards and the odd wild print, each one hand-picked and priced to wear.</p><a class="ulink" href="{clo}#ties">Shop ties</a></div></div>
  </section>

  {article(arts[0], False, True) if arts[0] else ''}

  <section class="duo">
    <div class="tile">{ph('img/shirts.webp', 'Man in a gingham shirt and pleated trousers by the sea', 'center 18%')}
      <div class="copy"><p>The oxford cloth button-down is the backbone of a good wardrobe. Gitman, Ralph Lauren and Brooks, with the collar roll that newer shirts never quite get right.</p><a class="ulink" href="{clo}#shirts">Shop shirts</a></div></div>
    <div class="tile">{ph('img/trousers.webp', 'Man in a leather jacket, striped tie and wide black trousers against a blue wall', 'center 10%')}
      <div class="copy"><p>Pleated chinos, madras shorts and white denim. Trousers cut with a little room, the way they were made before everything got skinny.</p><a class="ulink" href="{clo}#trousers">Shop trousers</a></div></div>
  </section>

  {article(arts[1], True, False) if arts[1] else ''}

  <section class="focus" aria-labelledby="focus-h">
    {ph('img/focus-teal.webp', 'Man in a vintage teal windbreaker and ball cap against a teal wall', 'center 12%')}
    <div class="focus-in">
      <h2 id="focus-h">Product in Focus</h2>
      <div class="grid4">
{cards}
      </div>
    </div>
  </section>

  <section class="popups" id="popups">
    <div class="popups-in">
      <div>
        <p class="label eyebrow">Find us in person</p>
        <h2>Pop-ups</h2>
        <p>Racks of hand-picked vintage, set up around Tulsa. Come try things on.</p>
      </div>
      <ul class="events">
{events}
        <li class="none" id="noEvents"{none_hidden}>New dates are on the way. Instagram gets them first.</li>
      </ul>
    </div>
  </section>

  <section class="feature" id="about">
    <div class="txt">
      <p class="label kicker">About us</p>
      <h2>Your home for vintage and secondhand style</h2>
      <p>We specialize in classic menswear, but we like to think our pieces look good on everyone. Every garment is handpicked for character, craftsmanship and staying power. Dressing up, down or somewhere in between, {esc(c['name'])} has you covered.</p>
      <a class="ulink" href="{clo}">Shop the rack</a>
    </div>
    <div class="img">{ph('img/about.webp', 'Man in a navy jacket, light denim and two-tone loafers in a studio', 'center 6%')}</div>
  </section>

  <section class="ig">
    <h2>@oxfordclothmarket</h2>
    <p>New finds and fits, posted first on Instagram.</p>
    <a class="ulink" href="{esc(c['instagram'])}">Follow on Instagram</a>
  </section>
</main>

{self.footer('index')}"""
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "@id": c["site_url"] + "/#org", "name": c["name"], "url": c["site_url"] + "/",
             "logo": self.abs(self.assets.url("icon-512.png")) if not self.preview else self.assets.url("icon-512.png"),
             "description": c["description"], "foundingDate": c["founded"], "sameAs": [c["instagram"], c["ebay_store"]]},
            {"@type": "WebSite", "@id": c["site_url"] + "/#site", "name": c["name"], "url": c["site_url"] + "/",
             "publisher": {"@id": c["site_url"] + "/#org"}},
        ]}
        title = f"{c['name']} | Vintage menswear from Tulsa"
        head = self.head(title=title, description=c["description"], path="/", ld=ld)
        if self.preview:
            head = (f"<title>{esc(c['name'])}</title>\n"
                    '<meta name="claude:viewport-fit-sides" content="cover">\n'
                    '<link rel="preconnect" href="https://fonts.googleapis.com">\n'
                    '<link rel="stylesheet" href="https://fonts.googleapis.com/css2?family=Libre+Caslon+Text:ital,wght@0,400;0,700;1,400&amp;family=Jost:wght@400;500&amp;display=swap">\n'
                    f'<link rel="stylesheet" href="{self.assets.url(self.assets.css)}">\n'
                    f'<script src="{self.assets.url(self.assets.js)}" defer></script>')
        return self.document(head, body, fragment=self.preview)

    def clothing(self, updated: str) -> str:
        c = self.cfg
        counts = {k: sum(1 for p in self.products if p["category"] == k) for k, _ in self.cats}
        chips = f'<a href="#all" data-k="all" data-label="All">All<span class="n">{len(self.products)}</span></a>' + "".join(
            f'<a href="#{k}" data-k="{k}" data-label="{esc(l)}">{esc(l)}<span class="n">{counts[k]}</span></a>' for k, l in self.cats)
        sizes = "(max-width:900px) 50vw, (max-width:1100px) 33vw, 25vw"
        cards = "\n".join(f"""    <a class="item" data-cat="{p['category']}" href="{esc(p['url'])}">
      <div class="shot">{self.img(p['variants'][600], p['name'], srcset=self.product_srcset(p), sizes=sizes, lazy=n >= 4, priority=n == 0)}</div>
      <h2>{esc(p['name'])}</h2>
      <div class="meta"><span>{esc(p['detail'])}</span><b>{self.money(p['price'])}</b></div>
      <span class="ulink">View on eBay</span>
    </a>""" for n, p in enumerate(self.products))
        when = dt.date.fromisoformat(updated)
        body = f"""{self.header('clothing')}
<main id="main">
  <section class="shop-intro">
    <h1 id="shopTitle">Clothing</h1>
    <p>Every piece is one of one: handpicked, cleaned and photographed by us. Tap any piece to buy it on eBay.</p>
    <nav class="chips" aria-label="Filter by category">{chips}</nav>
  </section>
  <section class="rack" aria-label="Pieces for sale">
{cards}
  </section>
  <div class="empty" id="empty"{' hidden' if self.products else ''}>
    <h2>Nothing here right now</h2>
    <p>New pieces go up most weeks. Instagram gets them first.</p>
    <a class="ulink" href="{esc(c['instagram'])}">Follow on Instagram</a>
  </div>
  <p class="note">Prices and availability from eBay as of {when.strftime('%B')} {when.day}, {when.year}. If a piece has sold, the eBay listing will say so.</p>
</main>
{self.footer('clothing')}"""
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "CollectionPage", "name": f"Clothing | {c['name']}", "url": self.abs("/clothing"),
             "isPartOf": {"@id": c["site_url"] + "/#site"}, "numberOfItems": len(self.products)},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": c["name"], "item": c["site_url"] + "/"},
                {"@type": "ListItem", "position": 2, "name": "Clothing", "item": self.abs("/clothing")}]},
        ]}
        head = self.head(title=f"Clothing | {c['name']}",
                         description=f"Shop {len(self.products)} one-of-one vintage pieces: shirts, tailoring, trousers and silk ties from Brooks Brothers, Ralph Lauren, Gitman and more.",
                         path="/clothing", ld=ld)
        return self.document(head, body)

    def not_found(self) -> str:
        body = f"""{self.header('404')}
<main id="main">
  <section class="notfound">
    <h1>Page not found</h1>
    <p>This page doesn't exist, or the piece that lived here has sold. The rest of the rack is still up.</p>
    <div class="links"><a class="ulink" href="{self.page('clothing')}">Shop clothing</a><a class="ulink" href="{self.page('index')}">Back to home</a></div>
  </section>
</main>
{self.footer('404')}"""
        head = self.head(title=f"Page not found | {self.cfg['name']}", description=self.cfg["description"], path="/404", noindex=True)
        return self.document(head, body)


# -------------------------------------------------------------- host files

def security_headers(cfg: dict) -> str:
    form = "'self'"
    if cfg.get("newsletter_action"):
        u = urlparse(cfg["newsletter_action"])
        form += f" {u.scheme}://{u.netloc}"
    csp = "; ".join([
        "default-src 'self'", "script-src 'self'", "style-src 'self' https://fonts.googleapis.com",
        "style-src-attr 'unsafe-inline'", "font-src https://fonts.gstatic.com", "img-src 'self' data:",
        "connect-src 'self'", f"form-action {form}", "frame-ancestors 'none'", "base-uri 'self'",
        "object-src 'none'", "upgrade-insecure-requests"])
    return f"""# Cloudflare Pages / Netlify response headers (generated by build.py)
/*
  Content-Security-Policy: {csp}
  Strict-Transport-Security: max-age=31536000; includeSubDomains
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: camera=(), microphone=(), geolocation=(), payment=(), usb=()
  Cross-Origin-Opener-Policy: same-origin

/assets/*
  Cache-Control: public, max-age=31536000, immutable

/img/*
  Cache-Control: public, max-age=86400, stale-while-revalidate=604800
"""


def build(preview: bool = False, out: Path | None = None, today: dt.date | None = None) -> Path:
    today = today or dt.date.today()
    out = out or ROOT / ("preview" if preview else "dist")
    cfg = validate_config(load_json(ROOT / "config.json"))
    cats = {k for k, _ in cfg["categories"]}
    pdata = load_json(ROOT / "data/products.json")
    products = validate_products(pdata, cats, ROOT / "media/products")
    events = validate_events(load_json(ROOT / "data/events.json"))
    articles = validate_articles(load_json(ROOT / "data/editorial.json"), ROOT / "media/mood")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    assets = Assets(out, "" if preview else "/")
    assets.css = assets.fingerprint(ROOT / "src/styles.css")
    assets.js = assets.fingerprint(ROOT / "src/site.js")
    assets.copy(ROOT / "media/brand/logo.webp", "img/logo.webp")
    for f in sorted((ROOT / "media/mood").glob("*.webp")):
        assets.copy(f, f"img/{f.name}")
    for p in products:
        p["variants"] = assets.product_variants(ROOT / "media/products" / p["image"], p["id"])
    assets.icons(ROOT / "media/brand/logo.webp")
    assets.og = assets.social_image(ROOT / "media/mood/hero.webp")
    (out / "site.webmanifest").write_text(json.dumps({
        "name": cfg["name"], "short_name": "OCM", "start_url": "/", "display": "browser",
        "background_color": "#F2EADB", "theme_color": "#F2EADB",
        "icons": [{"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]}, indent=1))

    site = Site(cfg, products, events, articles, assets, preview, today)
    (out / "index.html").write_text(site.index(), encoding="utf-8")
    (out / "clothing.html").write_text(site.clothing(pdata["updated"]), encoding="utf-8")
    if not preview:
        (out / "404.html").write_text(site.not_found(), encoding="utf-8")
        (out / "robots.txt").write_text(f"User-agent: *\nAllow: /\n\nSitemap: {cfg['site_url']}/sitemap.xml\n")
        urls = "".join(f"  <url><loc>{esc(cfg['site_url'] + p)}</loc><lastmod>{today.isoformat()}</lastmod></url>\n"
                       for p in ("/", "/clothing"))
        (out / "sitemap.xml").write_text(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n{urls}</urlset>\n')
        (out / "_headers").write_text(security_headers(cfg))
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--preview", action="store_true", help="build the Claude preview instead of the production site")
    args = ap.parse_args(argv)
    try:
        out = build(preview=args.preview)
    except BuildError as exc:
        print(f"Build failed: {exc}", file=sys.stderr)
        return 1
    files = sum(1 for f in out.rglob("*") if f.is_file())
    size = sum(f.stat().st_size for f in out.rglob("*") if f.is_file())
    print(f"Built {out.relative_to(ROOT)}/: {files} files, {size / 1024:.0f} KB")
    return 0


if __name__ == "__main__":
    sys.exit(main())
