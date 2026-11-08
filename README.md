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
| Build | `build.py`: Python 3.10+ and Pillow |
| Hosting | Cloudflare Pages (static files on a global CDN) |
| Tests | 94: build, content and data checks, plus real-browser tests |
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
config.json ─┐
data/*.json ─┼─> build.py ─> validate ─> escape ─> render ─> dist/
media/      ─┤                                               ├─ index.html, clothing.html, 404.html
src/        ─┘                                               ├─ assets/ (fingerprinted CSS + JS)
                                                             ├─ img/ (sized product photos)
                                                             └─ _headers, robots.txt, sitemap.xml
```

1. **Validate.** Every product, event and setting is checked first. A bad
   price, an unknown category, a missing photo or a link that isn't an eBay
   listing stops the build with a message naming the problem. The last good
   `dist/` is left alone.
2. **Escape.** All text is HTML-escaped, so product data from an automated
   eBay sync can never inject markup or scripts.
3. **Render.** Pages share one header, footer, stylesheet and script. Images
   get their real dimensions and phone-sized copies, and CSS and JS get
   content-hashed filenames so browsers can cache them for a year.

## Updating the site

Most changes are data edits. See [docs/CONTENT.md](docs/CONTENT.md) for
step-by-step instructions.

| To change | Edit |
| --- | --- |
| Products, prices, Product in Focus | `data/products.json` and `media/products/` |
| Pop-up dates | `data/events.json` (past dates drop off automatically) |
| Editorial teasers | `data/editorial.json` ("Read more" appears once an article has a `url`) |
| Domain, social links, newsletter | `config.json` |
| Styles and behavior | `src/styles.css`, `src/site.js` |

## Repository layout

```text
.github/workflows/  CI on every push and pull request, deploy to Cloudflare Pages
build.py            site generator
config.json         site settings
data/               products, events, editorial teasers
docs/               content guide, deployment guide, engineering audit
media/              source images: brand, mood photography, product photos
src/                styles.css and site.js
tests/              pytest suites and run_all.sh
tools/serve.py      local server that mimics Cloudflare Pages
```

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
- **Tested.** 94 tests, including browser checks at 320, 390, 768, 1024 and
  1440px wide against the production security headers.

## Documentation

- [docs/CONTENT.md](docs/CONTENT.md): adding products, events and articles
- [docs/DEPLOYMENT.md](docs/DEPLOYMENT.md): Cloudflare Pages, the domain and automatic deploys
- [docs/AUDIT.md](docs/AUDIT.md): engineering audit, findings and test coverage
- [docs/IMAGE-CREDITS.md](docs/IMAGE-CREDITS.md): where every image comes from
- [CHANGELOG.md](CHANGELOG.md)

## License

Copyright © 2026 Oxford Cloth Market. All rights reserved. See [LICENSE](LICENSE).
