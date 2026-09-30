# Launch execution status — 2026-09-30

Prepared-launch audit executed 2026-09-30. Findings: the launch is already
substantially executed. Everything below was re-verified live on this date.

## DONE (with evidence)

| Step | Status | Evidence |
|---|---|---|
| Repo public | DONE | `rorshopping/whisper-dictate` visibility = PUBLIC (gh repo view) |
| GitHub releases | DONE | v1.0.0…v1.0.3 all published; **v1.0.3 = Latest** (published 2026-09-20T22:55Z) with assets `WhisperDictate-v1.0.3-windows-x64.zip` (367 MB, 3 downloads) and `WhisperDictate-v1.0.3-macos-arm64-notarized.zip` (318 MB, 2 downloads) |
| Website live | DONE | https://whisperdictate.vercel.app/ → 200 (privacy/terms/impressum/thanks 200 via clean URLs; `.html` 308 → clean path by design) |
| Buy button wiring | DONE | `website/index.html` points at the live payment link (3 references) |
| Activation API | DONE | `/api/activate` `/api/validate` `/api/trial` deployed — GET returns 405 (POST-only); `POST /api/trial {}` returns proper JSON validation error |
| Stripe payment link | DONE | https://buy.stripe.com/9B614g0wY5i52nKg0C9AA03 → 200 (live mode, €40/yr — see STRIPE.md) |
| X launch post | DONE | https://x.com/RichardBcker1/status/2088034929162465574 + link reply (posted 2026-09-20, see MARKETING-LAUNCH.md) |
| Product Hunt | **LIVE (verified 2026-09-30)** | https://www.producthunt.com/products/whisper-dictate launched 2026-09-21 ("Launched 9d ago") — 1 point (maker upvote), 1 follower, 0 comments, not featured. Maker-comment engagement still outstanding |
| Community edition preview | DONE | `rorshopping/whisper-dictate-community` releases `community-v0.1.0` (pre-release) + `model-mirror-v1`; site https://whisper-dictate-community-web.vercel.app → 200 |
| Local commits pushed | DONE | 38 commits pushed to `origin/master` 2026-09-30 (HEAD `cc31329`). First push failed: two ~2.4 GB Nemotron `model.safetensors` blobs (GitHub hard limit 100 MB) had been committed under a stray `--doctor/` cache dir in `30774ae`/`e63c1ec`. Fixed by rewriting only the unpushed range with `git filter-repo --invert-paths --path="--doctor" --refs 46813e3..HEAD` (installed via pip); final tree unchanged, HEAD now `cc31329` |

## Notes

- **No GO-SEQUENCE.md / PUBLISH-CHECKLIST.md / product-launch/ exist** in this
  repo (the launch plan referenced elsewhere was never committed). This file is
  the replacement record.
- **dist staleness:** `dist/WhisperDictate/WhisperDictate.exe` (2026-09-20
  19:36) matches the published v1.0.3 build. Two functional fixes landed
  **after** v1.0.3: `5801151` (Hugging Face resolve URLs) and `ab37fbf`
  (frozen doctor mode), plus test/docs work. No v1.0.4 has been cut.
- Canonical build path is CI: pushing a `v*` tag runs `.github/workflows/
  release.yml` (tests → PyInstaller → release_guard/manifest → draft release);
  signing/notarization remain manual operator gates
  (NOTES_release-hygiene.md). A local rebuild would not match published
  checksum provenance, so none was made.

## Remaining steps to first customer

1. **Verify the Product Hunt launch went live** — DONE 2026-09-30, see table.
   Still open: light maker-comment engagement on the PH page.
2. **Show HN + Reddit r/SideProject** — DONE 2026-09-30. Reddit posted live:
   https://www.reddit.com/r/SideProject/comments/1wuaysg/ (u/englishmaster33).
   Show HN drafted at `product-launch/show-hn.md` — awaiting orchestrator
   review before posting to news.ycombinator.com.
3. **v1.0.4**: DONE 2026-09-30 — tag `v1.0.4` on `4d0bb22` (HF resolve URLs
   `5801151`, frozen doctor mode `ab37fbf`, plus the CI-caught community-export
   path-canonicalisation fix). CI produces the draft release; sign/notarize +
   attach per NOTES_release-hygiene.md remains a manual operator gate.
4. **Monitor first sale**: `stripe checkout_sessions list --live --limit 10`
   (see STRIPE.md). Optional: add the live-mode webhook secret to Vercel env
   `STRIPE_WEBHOOK_SECRET` (fast-path only; activation works without it).
5. Optional: `SMTP_USER`/`SMTP_PASS` secrets for the "Message customers"
   workflow, or `scripts/message_outlook.ps1` (STRIPE.md).
