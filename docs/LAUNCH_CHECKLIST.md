# Launch checklist

The state of the release, in the order the remaining work has to happen.

## 1. Artifacts

| Platform | Built where | Status |
|---|---|---|
| macOS arm64 | this Mac (`scripts/build_release.sh --zip`) | **done** — 21/21 self-check, model loads on MPS in 2.4 s, nested signatures verified |
| Windows x64 | `beckerhub-pc-tail` (`win_build.ps1`) | building — clean CPU-torch venv, unit tests run before freezing |
| Linux x86_64 | `wdlinux` Lima VM, Debian 12 (`scripts/build_release_linux.sh --tar`) | building |

Both remaining builds must report their own `--doctor` result before they count.
The Windows build has no code-signing certificate, so its zip is named
`-unsigned` and the page labels it "Unsigned preview".

## 2. Publish

```bash
cd ~/Documents/projects/whisper-dictate
./scripts/publish_release.sh dist/WhisperDictate-1.1.0-*.zip dist/WhisperDictate-1.1.0-linux-*.tar.gz
```

The script uploads to `rorshopping/whisper-dictate-releases` and then fetches the
first asset URL anonymously: a `200` proves the download works for a visitor who
is not signed in to GitHub (`curl -sI <url>`). Anything other than `200` means the
artifact is not actually downloadable and the script fails.

## 3. Deploy the website

The page is `/whisper-dictate` in `becker-hub-web` (Next.js on Vercel). It is
nav-linked on desktop, in the footer, in the sitemap, and it reads the release
feed at request time with a one-hour cache — so a new artifact appears without a
redeploy, but the **page itself** needs one deploy:

```bash
cd ~/Documents/projects/becker-codehub/becker-hub-web
git add -A && git commit -m "Add Whisper Dictate product page"
npx vercel --prod          # requires `npx vercel login` first; there is no token on this machine
```

Verified locally before deploying: `npm run build` succeeds and the page
prerenders; `scrollWidth == clientWidth` at 390/640/768/1440 px (no horizontal
overflow); the hero heading, download row, comparison table, feature list,
platform notes and FAQ are all present at mobile width.

## 4. Post the thread

`docs/LAUNCH_TWEETS.md` holds an 8-tweet thread plus a single-post variant.
`scripts/check_tweets.py` counts each tweet the way X does (URLs = 23 chars,
emoji = 2) and currently reports every tweet inside 280.

Before posting:

* attach one real screenshot to tweet 1 — the dictation tape or the status pill;
  the thread promises local processing and a stock gradient would undercut that
  in the first second
* if the Windows/Linux artifacts are not published yet, tweet 8's link still
  works: the page renders with every platform falling back to "See releases"
  instead of a dead button

## What is deliberately not done

* **No code signing.** macOS has no Developer ID certificate and Windows has no
  trusted Authenticode certificate. Both gaps are displayed to the user rather
  than papered over: the download page prints "Unsigned preview", and the
  Windows build script refuses to produce a zip that claims to be signed.
  `docs/BUILD_MACHINES.md` says exactly which certificate to create.
* **No GitHub workflow.** The user asked for none. Signing on the machines that
  own the keys is also the correct architecture for the macOS and Windows cases;
  the Linux build in a VM is reproducible from `packaging/lima-linux-build.yaml`.
* **No Linux arm64 or Windows arm64 build.** Neither was requested and neither
  can be validated here.
* **The `build/` deletions in the `becker-codehub` checkout are pre-existing**
  (parent directory mtime Sep 2). They are recoverable with
  `git checkout -- build/` if they were not intentional.
