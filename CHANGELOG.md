# Changelog

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
