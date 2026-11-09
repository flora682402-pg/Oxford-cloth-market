#!/usr/bin/env python3
"""Build the Oxford Cloth Market website.

    python3 build.py              # production site  -> dist/
    python3 build.py --preview    # Claude preview    -> preview/

Inputs: config.json, data/*.json, src/ (CSS + JS), media/ (images).
Needs Python 3.10+, Pillow and Jinja2. Page HTML lives in templates/. Every piece of data is validated and
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

from jinja2 import Environment, FileSystemLoader, StrictUndefined
from markupsafe import Markup
from PIL import Image

ROOT = Path(__file__).resolve().parent
PRODUCT_WIDTHS = (400, 600)  # 600 is the source size; 400 serves phones
PHOTO_WIDTHS = (640, 1024, 1200, 1600, 2400)  # lifestyle photos; the browser picks one per screen
PHOTO_EXTS = (".jpg", ".jpeg", ".png", ".webp")
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


def validate_home(data: dict, categories: set[str], media: Path) -> dict:
    """data/home.json: homepage photo tiles (rows of two) and section photos."""
    pos = re.compile(r"^(left|center|right|\d{1,3}%) \d{1,3}%$")

    def photo(p, where, *extra):
        for key in ("image", "alt", "position") + extra:
            if not isinstance(p.get(key), str) or not p[key].strip():
                raise BuildError(f"home.json {where}: missing {key}")
        if "/" in p["image"] or not (media / p["image"]).is_file():
            raise BuildError(f"home.json {where}: image {p['image']!r} not found in media/mood")
        if not pos.match(p["position"]):
            raise BuildError(f"home.json {where}: position must look like 'center 20%'")

    if not data.get("hero", {}).get("alt"):
        raise BuildError("home.json hero: missing alt")
    rows = data.get("rows")
    if not isinstance(rows, list) or not rows:
        raise BuildError("home.json: 'rows' must be a non-empty list")
    for r, row in enumerate(rows):
        if not isinstance(row, list) or len(row) != 2:
            raise BuildError(f"home.json row {r}: each row needs exactly two tiles")
        for i, tile in enumerate(row):
            photo(tile, f"row {r} tile {i}", "copy", "category", "link")
            if tile["category"] not in categories:
                raise BuildError(f"home.json row {r} tile {i}: unknown category {tile['category']!r}")
    for key in ("focus", "about"):
        photo(data.get(key, {}), key)
    return data


# ------------------------------------------------------------------ assets

_VARIANT_CACHE: dict[tuple, bytes] = {}


def _encode_variant(src: Path, mtime: int, width: int, quality: int = 80) -> bytes:
    """Resize/encode one image width as WebP (memoised within a process)."""
    # Keyed on the file's name, size and timestamp (not its folder), so test
    # copies of the project reuse the work instead of re-encoding every photo.
    key = (src.name, src.stat().st_size, mtime, width, quality)
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
            im.save(buf, "WEBP", quality=quality, method=6)
        _VARIANT_CACHE[key] = buf.getvalue()
    return _VARIANT_CACHE[key]

class Assets:
    """Copies/creates every static file and remembers image dimensions."""

    def __init__(self, out: Path, prefix: str):
        self.out, self.prefix, self.dims, self.photos = out, prefix, {}, {}

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

    def photo_variants(self, src: Path) -> dict[int, str]:
        """Lifestyle photo -> WebP at each PHOTO_WIDTHS size up to its own width.
        Never upscales: a photo narrower than 2400px tops out at its own width."""
        with Image.open(src) as im:
            natural = im.width
        widths = [w for w in PHOTO_WIDTHS if w < natural] + [min(natural, PHOTO_WIDTHS[-1])]
        out = {}
        for w in sorted(set(widths)):
            rel = f"img/{src.stem}-{w}.webp"
            dest = self.out / rel
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(_encode_variant(src, src.stat().st_mtime_ns, w, quality=78))
            self._record(rel, dest)
            out[w] = rel
        self.photos[src.name] = out
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
        rel = "img/og.jpg"  # link previews: 1200px wide is what social sites display
        with Image.open(src) as im:
            im = im.convert("RGB")
            if im.width > 1200:
                im = im.resize((1200, round(im.height * 1200 / im.width)), Image.LANCZOS)
            im.save(self.out / rel, "JPEG", quality=84, optimize=True, progressive=True)
        self._record(rel, self.out / rel)
        return rel


# ----------------------------------------------------------------- markup

class Site:
    """Renders the pages from templates/. Templates hold the HTML; this class
    only prepares the data they need and the helpers they call."""

    def __init__(self, cfg, products, events, articles, home, assets: Assets, preview: bool, today: dt.date):
        self.cfg, self.products, self.articles, self.home = cfg, products, articles, home
        self.assets, self.preview, self.today = assets, preview, today
        self.events = [e for e in events if dt.date.fromisoformat(e["date"]) >= today]
        self.env = Environment(loader=FileSystemLoader(ROOT / "templates"), autoescape=True,
                               undefined=StrictUndefined, keep_trailing_newline=True)
        self.env.globals.update(
            cfg=cfg, year=today.year, page=self.page, abs=self.abs, asset=assets.url,
            dims=lambda rel: assets.dims[rel], srcset=self.product_srcset, money=self.money,
            photo_src=self.photo_src, photo_srcset=self.photo_srcset,
            css=assets.css, js=assets.js,
            og={"url": assets.url(assets.og) if preview else self.abs(assets.og),
                "width": assets.dims[assets.og][0], "height": assets.dims[assets.og][1]})

    # Links differ between the real site (clean URLs) and the preview (files).
    def page(self, name: str) -> str:
        if self.preview:
            return {"index": "index.html", "clothing": "clothing.html"}[name]
        return {"index": "/", "clothing": "/clothing"}[name]

    def abs(self, path: str) -> str:
        return self.cfg["site_url"] + ("" if path.startswith("/") else "/") + path

    def photo_src(self, image: str) -> str:
        """Fallback src for browsers without srcset: the 1600px copy, or the largest."""
        v = self.assets.photos[image]
        return v[1600] if 1600 in v else v[max(v)]

    def photo_srcset(self, image: str) -> str:
        return ", ".join(f"{self.assets.url(rel)} {w}w" for w, rel in sorted(self.assets.photos[image].items()))

    def product_srcset(self, p: dict) -> str:
        return ", ".join(f"{self.assets.url(rel)} {w}w" for w, rel in p["variants"].items())

    @staticmethod
    def money(price: str) -> str:
        return "$" + (price[:-3] if price.endswith(".00") else price)

    def render(self, template: str, *, here: str, title: str, description: str, path: str,
               ld=None, noindex=False, fragment=False, **context) -> str:
        return self.env.get_template(template).render(
            here=here, title=title, description=description, path=path, noindex=noindex,
            fragment=fragment, ld=Markup(json_ld(ld)) if ld else None, **context)

    # --- pages
    def index(self) -> str:
        c = self.cfg
        events = [dict(e, label=dt.date.fromisoformat(e["date"]).strftime("%a · %b"),
                       day=dt.date.fromisoformat(e["date"]).day) for e in self.events]
        featured = sorted((p for p in self.products if p.get("featured")), key=lambda p: p["featured"]["order"])[:4]
        logo = self.assets.url("icon-512.png") if self.preview else self.abs(self.assets.url("icon-512.png"))
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "Organization", "@id": c["site_url"] + "/#org", "name": c["name"], "url": c["site_url"] + "/",
             "logo": logo, "description": c["description"], "foundingDate": c["founded"],
             "sameAs": [c["instagram"], c["ebay_store"]]},
            {"@type": "WebSite", "@id": c["site_url"] + "/#site", "name": c["name"], "url": c["site_url"] + "/",
             "publisher": {"@id": c["site_url"] + "/#org"}},
        ]}
        return self.render("index.html", here="index", title=f"{c['name']} | Vintage menswear from Tulsa",
                           description=c["description"], path="/", ld=ld, fragment=self.preview,
                           home=self.home, articles=self.articles, featured=featured, events=events)

    def clothing(self, updated: str) -> str:
        c = self.cfg
        when = dt.date.fromisoformat(updated)
        ld = {"@context": "https://schema.org", "@graph": [
            {"@type": "CollectionPage", "name": f"Clothing | {c['name']}", "url": self.abs("/clothing"),
             "isPartOf": {"@id": c["site_url"] + "/#site"}, "numberOfItems": len(self.products)},
            {"@type": "BreadcrumbList", "itemListElement": [
                {"@type": "ListItem", "position": 1, "name": c["name"], "item": c["site_url"] + "/"},
                {"@type": "ListItem", "position": 2, "name": "Clothing", "item": self.abs("/clothing")}]},
        ]}
        return self.render(
            "clothing.html", here="clothing", title=f"Clothing | {c['name']}",
            description=f"Shop {len(self.products)} one-of-one vintage pieces: shirts, tailoring, trousers and silk ties from Brooks Brothers, Ralph Lauren, Gitman and more.",
            path="/clothing", ld=ld, products=self.products,
            counts={k: sum(1 for p in self.products if p["category"] == k) for k, _ in c["categories"]},
            updated=f"{when.strftime('%B')} {when.day}, {when.year}")

    def not_found(self) -> str:
        return self.render("404.html", here="404", title=f"Page not found | {self.cfg['name']}",
                           description=self.cfg["description"], path="/404", noindex=True)


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
    home = validate_home(load_json(ROOT / "data/home.json"), cats, ROOT / "media/mood")

    if out.exists():
        shutil.rmtree(out)
    out.mkdir(parents=True)
    assets = Assets(out, "" if preview else "/")
    assets.css = assets.fingerprint(ROOT / "src/styles.css")
    assets.js = assets.fingerprint(ROOT / "src/site.js")
    assets.copy(ROOT / "media/brand/logo.webp", "img/logo.webp")
    for f in sorted(p for p in (ROOT / "media/mood").iterdir() if p.suffix.lower() in PHOTO_EXTS):
        assets.photo_variants(f)
    for p in products:
        p["variants"] = assets.product_variants(ROOT / "media/products" / p["image"], p["id"])
    assets.icons(ROOT / "media/brand/logo.webp")
    assets.og = assets.social_image(ROOT / "media/mood/hero.jpg")
    (out / "site.webmanifest").write_text(json.dumps({
        "name": cfg["name"], "short_name": "OCM", "start_url": "/", "display": "browser",
        "background_color": "#F2EADB", "theme_color": "#F2EADB",
        "icons": [{"src": "/icon-512.png", "sizes": "512x512", "type": "image/png"}]}, indent=1))

    site = Site(cfg, products, events, articles, home, assets, preview, today)
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
