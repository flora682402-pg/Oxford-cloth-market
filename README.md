# Oxford Cloth Market

The website for [Oxford Cloth Market](https://oxfordclothmarket.com), a
vintage and secondhand menswear shop in Tulsa, Oklahoma. Pieces sell through
the shop's [eBay store](https://www.ebay.com/str/oxfordclothmarket) and at
pop-up markets around Tulsa.

The site is static: plain HTML, one stylesheet and one small script, generated
from data files by a single Python script. It has no framework, no runtime
server and no database, so it is fast, inexpensive to host and hard to break.

## At a glance

| | |
| --- | --- |
| Pages | Home, Clothing (filterable by category), 404 |
| Build | `build.py` + `templates/`: Python 3.10+, Pillow and Jinja2 |
| Hosting | Cloudflare Pages (static files on a global CDN) |
| Tests | 113: build, content, data and template checks, plus real-browser tests |
| Checks on every push | Build, strict TypeScript check of the JavaScript, full test suite |
| Deploys | Automatic from `main` once Cloudflare is connected, plus a daily rebuild |

## Quick start

```sh
make setup     # install Python packages and the test browser
make build     # production site -> dist/
make serve     # http://127.0.0.1:8000, behaves like Cloudflare Pages
make test      # every check
```

No `make`? Run `python3 build.py`, `python3 tools/serve.py dist` and
`bash tests/run_all.sh` directly.

## How it works

```text
config.json  ─┐
data/*.json  ─┤
templates/   ─┼─> build.py ─> validate ─> render (Jinja2) ─> dist/
media/       ─┤                                              ├─ index.html, clothing.html, 404.html
src/         ─┘                                              ├─ assets/ (fingerprinted CSS + JS)
                                                             ├─ img/ (sized product photos)
                                                             └─ _headers, robots.txt, sitemap.xml
```

1. **Validate.** Every product, event and setting is checked first. A bad
   price, an unknown category, a missing photo or a link that isn't an eBay
   listing stops the build with a message naming the problem. The last good
   `dist/` is left alone.
2. **Render.** The HTML lives in `templates/` as Jinja2 templates. Pages share
   one layout, header and footer, and repeated pieces (photo tiles, product
   cards) are loops over data, not copies. Jinja2 escapes all text, so product
   data from an automated eBay sync can never inject markup or scripts, and a
   misspelled template variable stops the build instead of rendering blank.
3. **Optimize.** Images get their real dimensions and phone-sized copies, and
   CSS and JS get content-hashed filenames so browsers can cache them for a
   year. `build.py` contains no HTML; it validates data, prepares images and
   fills in the templates.

## Updating the site

Most changes are data edits. See [docs/CONTENT.md](docs/CONTENT.md) for
step-by-step instructions.

| To change | Edit |
| --- | --- |
| Products, prices, Product in Focus | `data/products.json` and `media/products/` |
| Pop-up dates | `data/events.json` (past dates drop off automatically) |
| Homepage photo tiles, their copy and crops | `data/home.json` |
| Editorial teasers | `data/editorial.json` ("Read more" appears once an article has a `url`) |
| Page layout and wording | `templates/` (one file per page, plus shared header and footer) |
| Domain, social links, newsletter | `config.json` |
| Styles and behavior | `src/styles.css`, `src/site.js` |

## Repository layout

| Path | What it holds |
| --- | --- |
| `build.py` | Site generator: validation, images, rendering |
| `templates/` | Page HTML: `base.html` layout, header, footer, one file per page |
| `data/`, `config.json` | Content and settings |
| `media/` | Source images: brand, lifestyle photography, product photos |
| `src/` | `styles.css` and `site.js` |
| `tests/` | pytest suites and `run_all.sh` |
| `tools/serve.py` | Local server that mimics Cloudflare Pages |
| `docs/` | Content guide, deployment guide, audit, image credits |
| `.github/workflows/` | CI on every push and pull request, deploy to Cloudflare Pages |

## Quality bar

- **Performance.** On a slow phone connection, both pages show their main
  content in under 0.9 seconds with zero layout shift.
  ([audit numbers](docs/AUDIT.md#measurements-before-and-after))
- **Security.** Strict content security policy, HSTS and anti-framing headers.
  No inline scripts and no secrets in the repository.
- **Accessibility.** WCAG AA text contrast, skip link, keyboard-operable menu,
  alt text on every image, and reduced-motion support.
- **SEO.** Canonical URLs, Open Graph images, structured data, sitemap and
  robots.txt.
- **Tested.** 113 tests, including browser checks from 320 to 3440px wide
  against the production security headers.

## Documentation

- [docs/CONTENT.md](docs/CONTENT.md): adding products, events and articles
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): moving DNS to Cloudflare, automatic deploys, the custom domain
- [docs/AUDIT.md](docs/AUDIT.md): engineering audit, findings and test coverage
- [docs/IMAGE-CREDITS.md](docs/IMAGE-CREDITS.md): where every image comes from
- [CHANGELOG.md](CHANGELOG.md)

## License

Copyright © 2026 Oxford Cloth Market. All rights reserved. See [LICENSE](LICENSE).
