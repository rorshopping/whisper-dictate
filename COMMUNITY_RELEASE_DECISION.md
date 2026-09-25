# Community Release Decision

Date: 2026-09-24

## Decisions

1. **Canonical source:** the current `master` line is the base for the community edition.
   The divergent `release/macos-1.1.0-verified` line and the public
   `whisper-dictate-releases` repository are release references only until their
   source and licensing are reconciled.

2. **Product split:** keep the paid product separate. The community edition is a
   free, no-account source distribution with no license activation, Stripe calls,
   or remote notice polling. Pro remains a separately built/published product.

3. **Application license:** use MIT for the community source, subject to the
   owner's confirmation that all included first-party code can be relicensed.
   Third-party dependencies and model weights retain their own licenses.

4. **Distribution:** the new community repository's GitHub Releases is the
   canonical binary host. The current paid repository and the alternate
   `whisper-dictate-releases` repository are not the community binary host.
   Vercel hosts only the website, documentation, and a generated release
   manifest. Model files use a separate object-storage mirror or an explicitly
   configured local model pack.

5. **Artifact matrix:** start with Windows x64 CPU portable and macOS Apple
   Silicon portable artifacts. Add signed installers and a separate CUDA build
   only after clean-machine qualification. Do not advertise Intel macOS or Linux
   as supported until matching artifacts and tests exist.

6. **Model source order:** verified local model directory/cache, project mirror,
   pinned Hugging Face snapshot, then explicitly selected optional engines.
   NVIDIA NIM and hosted APIs are never silent fallbacks. NeMo-Speech.cpp is a
   later, separately tested portable profile.

7. **Release quality gate:** clean worktree, locked dependencies and model
   revisions, tests, frozen smoke tests, package denylist, SBOM/license report,
   SHA-256, Windows signing, macOS notarization, and clean-machine acceptance
   before publication.

## Non-goals for the first community release

- No cloud transcription fallback.
- No automatic account creation or telemetry.
- No bundled multi-gigabyte model in the application executable.
- No claim of full offline capability before a verified model is installed.
- No reuse of the existing paid binaries under a new license.

## Canonical channel cleanup

The current paid site and the alternate free site must not both claim to be the
latest product. Before launch, select one canonical website and either archive,
redirect, or clearly mark the other channel as historical/preview.

**Outcome (2026-09-25):** the community site is canonical and published. The
older Becker Hub site was deliberately **kept online** rather than archived or
redirected; it now carries a banner naming the community edition as the
canonical free channel and linking the community site and the preview release
(commit `f790a91` in `rorshopping/becker-codehub`, deployed to
`https://becker-hub-web.vercel.app/whisper-dictate`). No content was removed
from the older channel.

## Execution update — 2026-09-25

The first public channel is now a **prerelease**, not a stable signed release:

- GitHub Releases: `https://github.com/rorshopping/whisper-dictate-community/releases/tag/community-v0.1.0`
- Vercel website/manifest: `https://whisper-dictate-community-web.vercel.app`
- macOS Apple Silicon portable ZIP: Developer ID signed, notarized, stapled, and Gatekeeper-assessed.
- Windows x64 portable ZIP: explicitly labeled unsigned preview; Authenticode signing remains a future gate.
- Installers, a project-controlled model mirror, and clean-machine acceptance with a real recording remain future work.

Follow-up decisions recorded 2026-09-25:

8. **Windows is unsigned by design, and the portable ZIP is the shipping
   format.** No Authenticode certificate is available, so the Windows artifact
   stays an explicitly unsigned portable ZIP
   (`WhisperDictate-0.1.0-windows-x64-portable-unsigned.zip`) with a
   `WhisperDictate-Portable.cmd` launcher. The earlier plain Windows ZIP is
   retained for continuity; the site points at the portable package.

9. **The Windows build is CPU-only, and the site says so.** The published
   archive bundles a CPU-only PyTorch build and no CUDA runtime, so the release
   notes, website, and third-party notices state this instead of implying GPU
   acceleration. A site test fails if the wording regresses.

10. **The older site stays online with a banner.** The legacy Becker Hub
    channel is not deleted or redirected; it is marked as the older channel and
    points visitors to the canonical community site and release.

11. **The SBOM is generated from the artifact, not the build machine.**
    `scripts/sbom_from_package.py` reads the `dist-info` metadata preserved in
    the frozen payload; `sbom-*.cdx.json` is published next to the binaries and
    `THIRD-PARTY-NOTICES.md` now carries the `rapidfuzz` MIT text that the first
    version of the notices wrongly claimed was unnecessary.

12. **A model mirror is provisioned, with the license question flagged.**
    Release `model-mirror-v1` in the public source repository publishes both
    pinned checkpoints as 15 assets (4.68 GiB), each weight file split into
    1.5 GB/1.05 GB parts because release assets cannot hold 2.4 GB files. A
    `whisper-dictate.model-mirror.v1` manifest describes them, and the resolver
    verifies every part, the assembled file, and the pinned revision before
    publishing anything to the cache. Hugging Face remains the last resort in
    `source_order`, so the mirror is a fallback, not a replacement. The mirror
    publication records the NVIDIA Open Model License and OpenMDW-1.1 notices;
    a human should still confirm the OpenMDW redistribution terms before a
    stable release, and a different model revision must be a new mirror tag.

13. **`hf-mirror.com` is explicitly rejected as a fallback.** It 308-redirects
    every request to huggingface.co regardless of user agent, so it cannot
    survive a blocked Hugging Face. The blocked-host test caught this; the
    documentation would not have.

14. **macOS ships a notarized disk image as well as a ZIP.** The image is gated
    by a macOS-produced verification record rather than by a filename, because
    the release guard cannot open a disk image off macOS. The record travels
    with the release.

The prerelease wording is intentional: it does not represent the paid product,
does not bundle model weights, and does not claim that the Windows artifact is
signed. Stable-release claims should wait for the remaining gates.
