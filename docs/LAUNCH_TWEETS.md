# Launch copy — NOT READY TO POST

Public launch is blocked. Only untrusted macOS/Windows previews exist; there is
no Linux artifact, and required signing credentials are missing. Do not post a
stable-release announcement or direct people to bypass OS security controls.

The previous launch thread has been withdrawn rather than retained as
copy-ready text. Its claims were not supported by release evidence:

| Withdrawn claim | Required correction or evidence |
|---|---|
| Downloads for Windows, macOS and Linux | No Linux artifact exists. macOS/Windows are untrusted previews, not approved releases. |
| All cloud tools cost $15/month, upload a live feed, and impose word allowances | Avoid universal competitor claims. Any comparison needs named products, current primary sources, dates, and comparable plans. |
| Replaces a $15/month subscription above 2,000 words/week | Unverified price, allowance, and functional-equivalence claims; remove. |
| CPU is fine; automatic CUDA/MPS acceleration | Benchmark the exact packaged builds. Source capability and local developer hardware do not establish packaged GPU support or adequate CPU performance. |
| Nothing is uploaded, ever; the network stays idle | Model setup requires downloads. Validate network behavior for each exact artifact; do not make absolute privacy guarantees. |
| It learns your words | User-maintained vocabulary and text replacement are not model learning or retraining. Describe them as corrections, not learning. |
| Spoken punctuation and snippets are both plain text files | Snippets use text files; punctuation is an opt-in setting backed by code. |
| “Scratch that” is something nobody else ships | Unsupported exclusivity claim; remove. Cursor-based deletion also needs limitations explained and packaged-build testing. |
| Everything is inspectable; the source is on GitHub | The source repository is private. A public release-assets repository is not public source access. Logs/history are not a complete audit. |
| First-use model download is a few hundred MB | Depends on the selected model/profile; measure before quoting a size. |
| Free, no account, no word limit | Confirm current distribution terms and exact artifact behavior before making launch promises. |

## Safe development-status draft (not a launch announcement)

**1/1**

> Whisper Dictate is still in preview. macOS and Windows builds are not yet trusted releases; signing and release validation remain outstanding. There is no Linux download yet. Public launch is on hold.

## Before restoring launch copy

- Complete the per-platform gates in `docs/LAUNCH_CHECKLIST.md`.
- Confirm that every platform named in the copy has an approved, accessible
  artifact and that the download page reports its actual status.
- Record model download requirements, packaged hardware support, and observed
  network behavior without turning limited tests into universal guarantees.
- Use a real screenshot only if it represents the offered build.
- Review factual claims separately from length checks. `scripts/check_tweets.py`
  is an approximate character-count helper, not factual or publication approval.
