# Channel Merge Audit

Date: 2026-09-24

## Decision

Do not merge or wholesale cherry-pick `origin/release/macos-1.1.0-verified` into the community integration branch. Keep the current integration branch as the source base and port only reviewed infrastructure changes.

## Channel findings

- Current source repository: `rorshopping/whisper-dictate`, public, current `master`, paid PolyForm product, latest `v1.0.3`.
- Alternate artifact repository: `rorshopping/whisper-dictate-releases`, public, `v1.1.0` assets for macOS arm64, unsigned Windows, and unsigned Linux.
- Alternate site: `becker-hub-web.vercel.app/whisper-dictate`, claims free/no-account/source-private, but the source branch is publicly readable and the release contains all three assets.
- The current and alternate sites/releases must not both be presented as the latest product.

## Valuable changes to port selectively

1. `app_paths.py` resource/data split, adapted to current consumers and migration rules.
2. Shared history locking from `d2a95da`, integrated with current `enhanced_features.py` and UI.
3. MacOS signing/validation gates, parameterized rather than copied with personal paths, team IDs, versions, or hashes.
4. Draft-only release publisher safety and checksum staging.
5. AppleDouble/default-file completeness checks.
6. Tk/build preflight and strict frozen model-load validation.

## Changes not to port wholesale

- Older `main.py`, `platform_mac.py`, settings/text tools, or config that would regress current smart formatting, voice commands, sounds, hotkeys, and long-recording handling.
- Hardcoded machine paths, certificate identities, team IDs, bundle IDs, versions, or artifact hashes.
- Linux build/support claims; the alternate branch's Linux instructions are internally inconsistent and validation is incomplete.
- Paid activation, Stripe, trial, remote notice, and source-private claims.
- Existing public binaries from either channel until provenance and licensing are explicitly cleared.

## Required reconciliation

- Select one canonical community source repository and artifact host.
- Select one canonical website/release manifest.
- Remove or clearly mark the alternate channel as historical/preview.
- Use a distinct community version namespace; do not ambiguously reuse `v1.0.3` or `v1.1.0`.
- Make release notes, asset lists, site status, source visibility, and signing status agree.
- Publish only Windows x64 CPU and macOS Apple Silicon initially; keep Linux experimental.

## Port order

1. Legal/channel confirmation and community runtime separation.
2. App paths and frozen defaults.
3. History store/shared locking.
4. Current-feature-compatible settings UI.
5. Parameterized macOS signing/validation.
6. Release workflow, checksums, archive guard, and clean-machine qualification.

The current paid `master` checkout remains untouched while this port plan is implemented on the isolated integration branch.
