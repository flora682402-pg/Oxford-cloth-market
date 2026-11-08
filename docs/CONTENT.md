# Updating the site's content

Every change on this page is a data edit followed by a rebuild. If something is
wrong, the build stops and says which line to fix. It never publishes a broken
page.

After any change, run `make build` and `make test`, or push to GitHub and let
the checks run there.

## Add a product

1. Save the photo to `media/products/` as a WebP or JPEG, about 600px wide and
   3:4 portrait, named after the eBay item number (for example
   `317189767758.webp`). The build makes the smaller phone version.
2. Add an entry to `items` in `data/products.json`:

```json
{
  "id": "317189767758",
  "category": "shirts",
  "brand": "Gitman Bros.",
  "name": "Gitman Bros. Vintage button-down",
  "detail": "Small · Made in USA",
  "price": "32.00",
  "currency": "USD",
  "url": "https://www.ebay.com/itm/317189767758",
  "image": "317189767758.webp"
}
```

- `category` must be one of `shirts`, `tailoring`, `trousers`, `ties` or
  `accessories`. The list lives in `config.json`.
- `price` always has two decimals (`32.00`). The site shows it as `$32`.
- `url` must be an `https://www.ebay.com/...` listing.
- Items appear on the Clothing page in the order they're listed.

Update `"updated"` at the top of the file to today's date. It appears on the
Clothing page as "Prices and availability from eBay as of ...".

## Remove a sold product

Delete its entry from `data/products.json`. You can also delete its photo, but
you don't have to.

## Change Product in Focus

The homepage shows the four items with a `featured` block, ordered by `order`:

```json
"featured": {
  "order": 1,
  "name": "Gitman Bros. Vintage button-down, made in USA",
  "detail": "Small",
  "alt": "Magenta Gitman Bros. Vintage button-down laid flat"
}
```

Use orders 1 through 4, each one only once. `alt` describes the photo for
screen readers and search engines.

## Add or remove a pop-up

Edit `data/events.json`:

```json
{ "date": "2026-11-21", "name": "Offline Tulsa Collective", "where": "Tulsa, OK",
  "url": "https://www.instagram.com/offlinetulsacollective" }
```

The weekday ("Sat · Nov") is worked out from the date. Past events disappear
on their own: the daily rebuild drops them, and visitors' browsers hide them
in between. When no dates are left, the section says new dates are on the way.

## Editorial teasers

`data/editorial.json` holds the two homepage articles. "Read more" only shows
once an article has a `url`, so there are never dead links.

## Site settings

`config.json` holds the domain (`site_url`), tagline, description, Instagram and
eBay links, the category list, and `newsletter_action`. Set that last one to
the form address from an email provider to turn on real newsletter sign-ups.
Until then, the form says sign-up opens soon and stores nothing.
