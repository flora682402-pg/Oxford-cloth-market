# Changelog

## 1.3.0 — 2026-11-10

### Added

- The homepage now tells search engines that Oxford Cloth Market is a
  clothing store serving Tulsa. Only the city is published, never a street
  address.
- Upcoming pop-ups are marked up as events, so Google can list them in event
  searches. Past dates drop out on the daily rebuild.
- `google_business` in `config.json`: once the Google Business Profile is
  public, paste its link there to connect it to the site.

## 1.2.0 — 2026-11-09

### Changed

- Replaced all 10 lifestyle photos with full-size Pexels originals (3–4× the
  resolution). The build now makes five sizes of each, and pages tell the
  browser which to pick, so photos are sharp on retina and ultrawide screens
  while phones still download small files.
- Social link previews now use a 1,200px image.

### Fixed

- Corrected the audit's phone performance figures, which were measured at 1×
  pixel density instead of an iPhone's 3×.

## 1.1.0 — 2026-11-09

### Changed

- Page HTML moved out of `build.py` into Jinja2 templates in `templates/`:
  a shared layout, header and footer, and one file per page. The build script
  now holds no HTML.
- Homepage photo tiles are a loop over `data/home.json` instead of four
  hand-written copies, so tile text, photos and crops are data edits.
- Output is identical to 1.0.1, verified tag-by-tag on every page of both the
  production and preview builds.

### Added

- Validation for `data/home.json`, and tests that a template typo fails the
  build and that no HTML returns to `build.py` (113 tests).

## 1.0.1 — 2026-11-09

### Fixed

- Photos no longer crop people's heads off on very wide monitors. The photo rows
  are now capped at the page width, each photo's crop is anchored on the person,
  and the desktop and phone hero images have separate crops.
- Product in Focus background now shows the teal jacket instead of a face
  behind the product cards.
- Added tests at 1920, 2560 and 3440px wide so this is caught automatically.

## 1.0.0 — 2026-11-08

First production release.

### Site

- Homepage: hero, tailoring and ties features, editorial teasers, Product in
  Focus, pop-up dates, about section and Instagram link.
- Clothing page with all 22 current eBay pieces and category filters.
- 404 page, favicon set, social preview image, sitemap and robots.txt.

### Engineering

- Data-driven static build with validation and HTML escaping.
- Security headers, including a strict content security policy.
- Phone-sized product images, image dimensions and load priorities. On a slow
  phone, Clothing page load dropped from 2.3s to 0.9s and data from 708 KB
  to 297 KB.
- WCAG AA contrast, skip link, keyboard-operable menu and reduced-motion
  support.
- 94 automated tests, strict TypeScript checking, CI on every push, and
  automatic deploys to Cloudflare Pages.

See [docs/AUDIT.md](docs/AUDIT.md) for the full audit.
