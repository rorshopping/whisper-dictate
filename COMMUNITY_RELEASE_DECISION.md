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
