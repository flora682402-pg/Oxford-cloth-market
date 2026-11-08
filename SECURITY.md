# Security

## Reporting a problem

If you find a security issue with oxfordclothmarket.com, message
[@oxfordclothmarket on Instagram](https://www.instagram.com/oxfordclothmarket)
and ask for a private contact. Please don't open a public GitHub issue.

## How the site is protected

- Static files only: no server code, database, logins or stored customer data.
- A strict Content-Security-Policy allows scripts only from the site itself,
  plus HSTS, anti-framing, nosniff, and referrer and permissions policies.
  All of these are generated in `build.py` (`security_headers()`).
- Purchases happen on eBay. The site never handles payment details.
- All content is validated and HTML-escaped at build time.
- No secrets live in this repository. Cloudflare deploy credentials are
  GitHub Actions secrets (see `docs/DEPLOYMENT.md`).
- Dependabot checks the Python packages and GitHub Actions monthly.
