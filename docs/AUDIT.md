# Engineering audit: Oxford Cloth Market website

Audited November 8, 2026. The site sells through eBay listings. The goal was
launch-grade engineering with no visual redesign.

## Summary

The original pages were fast and error-free in the browser, but not ready to
deploy. The homepage was not a complete HTML document, the newsletter form
claimed sign-ups it never stored, two links went nowhere, and the site had no
SEO metadata, security headers or 404 page. Product data was hand-typed into
HTML, which would have blocked the planned eBay auto-update.

All issues below are fixed except where marked. The site is now generated from
validated data by a small build script, covered by 94 automated tests, and
type-checked. Visually it matches the original, with the exceptions listed under
"Visible changes".

## Issues found, ranked, and status

| # | Severity | Issue | Status |
| --- | --- | --- | --- |
| 1 | Critical | Homepage had no doctype, `<html lang>` or `<head>`; it relied on the preview host and would render in quirks mode on a real domain | Fixed |
| 2 | Critical | Newsletter said "You're on the list" but saved nothing | Fixed: honest message now; posts to a provider once one is set in `config.json` |
| 3 | High | Two "Read more" links pointed at their own section | Fixed: shown only when an article URL exists |
| 4 | High | No meta description, canonical, Open Graph image, favicon, structured data, robots.txt or sitemap | Fixed |
| 5 | High | Products hard-coded in two places, no escaping for future eBay data | Fixed: `data/products.json`, validated and HTML-escaped |
| 6 | High | No security headers | Fixed: CSP, HSTS, nosniff, anti-framing, referrer and permissions policies |
| 7 | High | Orange labels 2.2:1 contrast (WCAG AA needs 4.5:1) | Fixed: 4.6:1 |
| 8 | Medium | No image dimensions; first products lazy-loaded; phones downloaded images about 3x larger than shown | Fixed: dimensions, priority hints, 400px phone images |
| 9 | Medium | Header, footer, CSS and JS duplicated per page | Fixed: shared templates, one CSS file, one JS file |
| 10 | Medium | Past pop-ups never disappeared | Fixed: removed at build time and hidden in the browser between builds |
| 11 | Medium | Menu jumps hid section titles under the sticky header | Fixed: scroll margin |
| 12 | Medium | Logo animation resized the element on scroll (layout work) | Fixed: transform-only, same sizes |
| 13 | Medium | Phone menu opened under the large logo; no Escape to close | Fixed: logo docks when menu opens; Escape closes and returns focus |
| 14 | Medium | No 404 page | Fixed |
| 15 | Low | No skip link; focus ring invisible on orange and oxblood sections; footer headings collapsed on desktop clicks; desktop nav not a landmark | Fixed |
| 16 | Low | Product in Focus photos rendered at uneven heights | Fixed (side effect of image dimensions) |
| 17 | Low | Google Fonts is a third-party request (privacy, one extra connection) | Partly: preconnect added. Self-hosting needs the font files, which could not be downloaded here |

## Measurements, before and after

Measured in Chromium. "Phone" is 390px wide on simulated slow 4G with a 4x CPU
slowdown. Google Fonts were blocked in both runs so the numbers are comparable.

| Page | Metric | Before | After |
| --- | --- | --- | --- |
| Clothing, phone | Largest Contentful Paint | 2,252 ms | 856 ms |
| Clothing, phone | Data transferred | 708 KB | 297 KB |
| Clothing, desktop | Data transferred | 1,655 KB | 628 KB |
| Home, phone | Largest Contentful Paint | 920 ms | 776 ms |
| Home, phone | Data transferred | 379 KB | 255 KB |
| All pages | Cumulative Layout Shift | 0 | 0 |
| All pages | Images without dimensions | 15 per page | 0 |
| All pages | Console errors, sideways scrolling | none | none |

Google treats LCP under 2,500 ms and CLS under 0.1 as "good". Both pages now
pass on a slow phone.

## Visible changes

- The small orange labels ("Editorial", "About us") are a darker orange so they
  can be read. Orange backgrounds, buttons and hover colors are unchanged.
- The two dead "Read more" links are gone until the articles exist.
- Product in Focus photos now line up at equal heights.
- The newsletter's message after submitting is now accurate.
- Pixel comparison: everything else matches within image-compression noise.
  The pages are 27px (desktop) and 78px (phone) shorter because of the
  removed links.

## Checks run

| Check | Result |
| --- | --- |
| Production build and preview build | Pass |
| TypeScript `--checkJs --strict` on site.js | 0 errors (found and fixed 1) |
| Python compile and unused-import scan | Pass |
| 54 build and content tests: markup well-formed, unique IDs, one H1, alt text and dimensions on every image, every local link and asset resolves, every in-page and cross-page anchor resolves, SEO tags, valid JSON-LD, sitemap, robots, headers, icons, fingerprinted assets, page-weight budget, copy preserved, escaping of hostile product names, rejection of 9 kinds of bad data, event expiry, newsletter wiring | 54 pass |
| 40 real-browser tests: 3 pages x 5 widths (320 to 1440px) for overflow and console or CSP errors, security headers, 404 status, clean-URL redirect, all images load, layout shift, phone menu (open, Escape, link tap), desktop nav, logo docking size, 5 filter states, filter clicks, newsletter, skip link, anchor clearance, footer behavior, event expiry on 3 future dates, JavaScript disabled, reduced motion | 40 pass |

## Not tested here, and why

- **Lighthouse, axe and the W3C HTML validator.** None of them are installed,
  and installing packages is blocked in this workspace. Equivalent checks were
  written into the tests instead. Run Lighthouse in Chrome DevTools after
  launch.
- **Safari, Firefox and real phones.** Only Chromium is available. The CSS and
  JS avoid features without broad support, and the menu falls back for
  Safari 13.
- **External links** (Instagram, eBay listings) and Google Fonts. Outside
  network access is blocked here, so these were checked by format only.
- **Real CDN behavior.** Headers and clean URLs were tested on a local server
  built to behave like Cloudflare Pages, not on Cloudflare itself.
- **Screen readers.** Landmarks, labels, alt text and focus order are in place,
  but they have not been tried with VoiceOver or NVDA.
- **White text over photos.** The gradient overlays keep it readable, but
  contrast over photos can't be measured reliably by machine.

## Still needs attention

1. **Domain: done.** `config.json` is set to `https://oxfordclothmarket.com`,
   which feeds canonical links, the sitemap and social previews.
2. **Newsletter provider.** Pick a free provider and set `newsletter_action`.
3. **Editorial articles.** Write them, or leave the teasers without links.
4. **Higher-resolution mood photos.** The hero is 1,125px wide and looks soft on
   large and retina screens. Download originals, and keep a note of where each
   stock photo came from and its license.
5. **Self-host the two fonts** to remove the Google dependency.
6. **eBay auto-update.** Run it as a scheduled job that rewrites
   `data/products.json` and rebuilds. Never call eBay on each page view: eBay
   rate-limits its API, and a viral day would hit the limit.
7. **Analytics.** None yet. Cloudflare Web Analytics is free and cookieless.
   Adding it needs one CSP change.

## Traffic and scale

The site is static files on a CDN, with no server or database to overload.
Cloudflare Pages serves static asset requests free and without limit, so a
traffic spike does not need any change to the site. The only per-visitor
third-party dependency is Google Fonts. Item 5 removes it.

For direct checkout later:

- **Per-product pages with real URLs** (for example `/clothing/shirts`, then one
  page per piece). Google only shows product rich results for single-product
  pages, so list-page product markup was deliberately left out.
- **One source of truth for inventory.** Every piece is one of one, so a sale on
  eBay must remove it from the site, and the reverse, before a second buyer can
  pay. Use a hosted checkout (Shopify, or Stripe Checkout with inventory sync)
  instead of handling card details on the site.
- The data-driven build already supports this. A sync job or a store backend
  writes the product data, and the same templates render it.
