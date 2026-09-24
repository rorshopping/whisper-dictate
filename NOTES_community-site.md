# Community site implementation notes

## Scope

Created an independent static site in `community-site/` for the free
Whisper Dictate Community Edition. The existing paid `website/` directory,
application code, release workflow, and license gate were intentionally left
untouched.

The site uses the existing dark visual language (deep navy panels, green/cyan
accents, compact cards, and terminal-style labels) but has its own HTML, CSS,
JavaScript, manifest, Vercel configuration, legal pages, and documentation.

## Release safety

- `community-site/releases.json` is the browser-facing source of truth.
- Its initial status is `placeholder`.
- All four requested artifacts (Windows x64 and macOS Apple Silicon, each with
  Portable ZIP and Installer choices) have `null` filenames, URLs, sizes, and
  checksums.
- `app.js` enables a download only when the manifest says `published`, the URL
  is HTTPS, and a filename is present. It never constructs a guessed download
  URL.
- Checksums are shown only for published artifacts with a 64-character SHA-256
  value.

## User-facing disclosures

The page distinguishes local/offline behavior after model acquisition from the
first-run Hugging Face download, links the source repository, calls out separate
software and model terms, and explains requirements, checksums, and common
Windows/macOS troubleshooting. It contains no Stripe/payment/telemetry claims.

## Deployment and validation

`community-site/vercel.json` is a small static configuration with clean URLs
and a restrictive same-origin Content Security Policy plus common security
headers. `community-site/scripts/validate_site.py` uses only Python's standard
library and performs offline HTML/link/manifest/header checks.

Validation command run:

```text
python community-site/scripts/validate_site.py
python -m unittest discover -s community-site/tests -p 'test_*.py'
```

Results: both passed with no network access.

No deployment, publishing, secret creation, or modification outside this
worktree was performed. The only commit for this work is:

`feat(community-site): add free edition download site`
