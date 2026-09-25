# Whisper Dictate community-release integration verification

**Verifier:** independent integration verifier

**Worktree:** `C:\Users\Richard\Documents\Projects\whisper-dictate_wt\integration`

**Branch:** `integration/community-release`

**Verification date:** 2026-09-25

**Python used for tests:** `C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe` (Python 3.12.10)

## Overall verdict

**Code/integration verification: PASS after the fixes recorded below.**

**Public release: BLOCKED** until the external release gates in the final section are completed.

The paid checkout was not edited. All changes made by this verification are in the integration worktree and are recorded in commit `588fcd7` (`fix: close community release packaging gaps`). The generated community product is the source export, not the paid root branch.

| Area | Status | Summary |
|---|---|---|
| Tree sanity and Python syntax | **PASS** | Clean start, no conflict markers, `git diff --check` clean, all tracked Python compiled. |
| Test suites | **PASS** | 131 root tests, 1 site test, 72 focused integration tests, and 85 exported-source tests passed; only the Windows symlink test was skipped because the required privilege is unavailable. |
| Community source export | **PASS** | Fresh export, manifest/hash verification, 21 exported Python files compiled, paid/runtime/private files absent. |
| Resolver and profile wiring | **PASS** | Legacy first-use behavior, strict explicit offline behavior, pinned revisions, source/mirror/cache settings, language checks, local-only Transformers loading, and faster-whisper compatibility verified. |
| Portable/resource/data paths | **PASS** | Frozen/resource separation, portable fallback, migration/merge, local overrides, sound lookup, shared lock, Unicode/space paths, and Windows data-root choice verified. |
| Release guard and manifests | **PASS** | Guard/manifest tests and smoke checks pass; model-weight/cache paths are now denied and manifest base URLs must be credential-free HTTPS. |
| Release workflow | **BLOCKED** | YAML/permissions/no-secret assumptions pass static review, but GitHub Actions and a real final archive were not runnable here. |
| Community site | **PASS (offline validation)** | Validator, link/ARIA/security-header checks, placeholder safety, and site tests pass; live Vercel deployment is not verified. |
| Installer templates | **PASS (static)** / **BLOCKED (platform execution)** | Text tests and credential scan pass; Inno Setup, macOS signing, notarization, and installer execution were not available. |

## 1. Tree sanity

### Start state

Command:

```text
git status --short --branch
```

Result at the beginning of verification:

```text
## integration/community-release
```

There were no modified or untracked files in the integration worktree at the start. The recent history included the resolver, portable-path, release-hygiene, site, packaging, and exporter merges, ending at `51c1c3b`.

Additional checks:

```text
git diff --check
```

Result: no output (clean).

An exact conflict-marker scan was run with `git grep` for lines beginning with `<<<<<<< `, `>>>>>>> `, or exactly `=======`; it returned no matches. The earlier broad `=======` search was not used as evidence because Markdown horizontal rules and license text contain repeated equals signs.

The specified interpreter reported:

```text
Python 3.12.10
```

Changed Python files were compiled in memory:

```text
CHANGED_PYTHON_FILES_COMPILED 19
```

All tracked Python files were also compiled:

```text
ALL_TRACKED_PYTHON_FILES_COMPILED 33
```

The full-tree compile command was:

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe -m compileall -q .
```

Result: exit code 0.

## 2. Tests

### Full root suite

Command:

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe -m unittest discover -s tests -p "test_*.py" -v
```

Final result:

```text
Ran 131 tests in 4.282s
OK (skipped=1)
```

The one skip is the directory-symlink exporter test on this Windows host (`WinError 1314`, required privilege not held). It is an environment limitation, not a test failure.

### Community-site suite and validator

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe -m unittest discover -s community-site/tests -p "test_*.py" -v
```

Result:

```text
Ran 1 test in 0.135s
OK
```

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe community-site/scripts/validate_site.py
```

Result:

```text
Community site validation passed: 3 HTML pages, 4 artifact placeholders, local links, manifest, and security headers checked.
```

### Focused path/model/export/release/packaging suite

Command:

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe -m unittest tests.test_app_paths tests.test_model_manager tests.test_nemotron_model_resolution tests.test_profile_model_wiring tests.test_community_export tests.test_release_hygiene tests.test_packaging -v
```

Final result:

```text
Ran 72 tests in 4.180s
OK (skipped=1)
```

The individual focused runs also passed: 9 profile-wiring tests, 20 model-manager/Nemotron tests, 15 app-path tests, 12 release-hygiene tests, 9 exporter tests, and 7 packaging tests.

## 3. Community source export

A fresh destination was used after the fixes:

```text
C:\Users\Richard\AppData\Local\Temp\opencode\community-export-verifier-20260925-03
```

Command:

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe scripts/export_community.py C:\Users\Richard\AppData\Local\Temp\opencode\community-export-verifier-20260925-03
```

Result:

```text
Community source export written to C:\Users\Richard\AppData\Local\Temp\opencode\community-export-verifier-20260925-03
```

Every exported Python file was compiled in memory:

```text
PYTHON_FILES 21
PYTHON_COMPILE_OK 21
```

The exported source tests also passed:

```text
Ran 85 tests in 0.287s
OK
```

The export manifest and file set were independently checked. Results:

```text
EXPORT_REQUIRED_FILES_OK 3
EXPORT_MANIFEST_VERIFIED 63
EXPORT_FORBIDDEN_SCAN_OK 14
EXPORT_PAID_SECRET_SCAN_OK
EXPORT_MODEL_WEIGHTS_ABSENT 17 suffixes
EXPORT_LOCAL_LOG_HISTORY_FILES_ABSENT
```

The required runtime files `app_paths.py`, `model_manager.py`, and `nemotron_engine.py` were present. The following were absent: `license_gate.py`, its test, `STRIPE.md`, `MARKETING-LAUNCH.md`, the paid website/API tree, `.github`, release scripts, local config, logs, transcription history, environment files, model weights, and Python caches. The generated `LICENSE`, `MODEL_LICENSES.md`, and `COMMUNITY_EXPORT_MANIFEST.json` were present as intended, and all 63 non-self entries matched their recorded sizes and SHA-256 hashes.

A community-export doctor smoke run was also made against a separate data root. It imported the application and passed config/dependency/microphone/clipboard/path checks. It returned exit code 1 only because neither 2.4 GB model is cached locally:

```text
17/19 checks passed.
DOCTOR_EXIT=1
```

That is expected for a source export that intentionally does not bundle model weights; it confirms first-use acquisition is still required.

The release guard was also run over the generated tree:

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe scripts/release_guard.py C:\Users\Richard\AppData\Local\Temp\opencode\community-export-verifier-20260925-03
```

Result:

```text
Release package guard passed (1 path(s)).
```

## 4. Model resolver and profile wiring

The focused resolver tests passed, including these explicitly named behaviors:

- `test_checked_in_legacy_top_level_offline_allows_first_download`
- `test_legacy_top_level_offline_allows_fresh_cache_download`
- `test_explicit_model_resolver_offline_is_strict_on_fresh_cache`
- `test_profile_offline_overrides_legacy_top_level_policy`
- `test_get_model_passes_resolver_options_to_mocked_engine`
- `test_resolver_failure_is_logged_and_re_raised_without_fallback`
- `test_faster_whisper_constructor_remains_unchanged`
- `test_offline_never_invokes_network`
- `test_transformers_load_is_local_only_and_revision_pinned`

The checked-in profile revisions were independently resolved against the embedded manifests:

```text
EN nvidia/nemotron-speech-streaming-en-0.6b ebe59e5a817142986528bbbee5dba8db7b38ed50 ('en',)
DE nvidia/nemotron-3.5-asr-streaming-0.6b ea30d66debe3740a08b573244286791d423d6b3e ('en', 'es', 'de', ...)
```

Static inspection of `model_manager.py`, `nemotron_engine.py`, and the resolver bridge found no paid API imports, Stripe/NIM/OpenAI fallback imports, or hosted transcription fallback. The Nemotron load tests verify `local_files_only=True`, pinned revision propagation, `trust_remote_code=False`, and re-raised resolver failures.

## 5. Portable paths

`tests.test_app_paths` passed all 15 tests. A separate Unicode/space-path probe also passed:

```text
PORTABLE_RESOURCE_DATA_SEPARATION_OK
UNICODE_SPACE_PORTABLE_PATH_OK ...\Installed App \u2713\PortableData
SHARED_LOCK_PATH_OK ...\PortableData\.app.lock
CONFIG_MIGRATION_MERGE_OK {'offline': True, 'sound': False, 'new': 1}
```

The current Windows data-root choice was printed directly:

```text
WINDOWS_USER_DATA_DIR C:\Users\Richard\AppData\Roaming\Whisper Dictate
SOURCE_MODEL_CACHE C:\Users\Richard\.cache\huggingface\hub
```

This matches the documented policy: frozen Windows data is under `%APPDATA%\Whisper Dictate`, while source mode retains the historical Hugging Face home cache. Tests and inspection also cover read-only portable fallback, resource-vs-data separation, atomic config writes/merge/migration, invalid-config preservation, local `*.local.txt` paths, bundled sound lookup, and the shared `.app.lock` abstraction.

## 6. Release guard, manifests, and workflow

### Static/tool checks

The workflow was parsed with PyYAML and its permission assumptions were asserted:

```text
WORKFLOW_YAML_PARSE_OK
WORKFLOW_PERMISSION_ASSERTIONS_OK
WORKFLOW_NO_SIGNING_SECRET_REFERENCES_OK
VERCEL_JSON_OK
```

The workflow has `contents: read` for build jobs, exactly one `contents: write` job, draft-only release attachment, `persist-credentials: false`, declared dependency installation, guard/manifest steps, and no signing-secret references.

A release-manifest smoke test generated two assets, verified sorted metadata and SHA-256 values, and verified HTTPS URLs:

```text
RELEASE_MANIFEST_SMOKE_OK 2
```

An archive containing `model.safetensors` was rejected by the guard:

```text
RELEASE_GUARD_MODEL_WEIGHT_REJECTED
```

The guard now also rejects `.ckpt`, `.pth`, `.pt`, `.onnx`, `.gguf`, `.h5`, `.pkl`, `.bin`, `models--*`, `model-cache`, and `huggingface` cache paths, while allowing ordinary package paths such as `transformers/models/...`.

### Build qualification status

The requested venv does not contain PyInstaller:

```text
C:\Users\Richard\Documents\Projects\whisper-dictate\.venv\Scripts\python.exe -m PyInstaller --version
No module named PyInstaller
```

A global PyInstaller 6.18.0/Python 3.14 executable was used only as a diagnostic. The first build exposed and fixed a real integration defect: the spec referenced missing `corrections-de.txt`. After adding that resource, a short-path build progressed through analysis and packaging but stopped at `COLLECT` with Windows `WinError 206` (path too long in the global environment's large PyTorch dependency tree). The local `build/` and `dist/` outputs were removed afterward.

Therefore:

- release guard/manifest behavior: **PASS**;
- real Windows PyInstaller archive in this environment: **BLOCKED**;
- GitHub Actions execution: **BLOCKED** (not run here);
- signing/notarization and final-archive hashing after signing: **BLOCKED** by design and operator gate.

## 7. Community site and installer templates

The site validator and its test passed. The validator checks three HTML documents, local links/fragments, one `h1`/`main`/title, skip links, ARIA references, duplicate IDs, inline event handlers, release manifest shape, HTTPS URLs, model URLs, and security headers. The site intentionally has four null artifact entries and disabled download controls until a real release is entered.

An independent safety scan produced:

```text
SITE_NO_PAID_OR_CREDENTIAL_MARKERS_OK
SITE_RELEASE_PLACEHOLDER True
```

The packaging static tests passed all 7 tests, including per-user Inno settings, no install-time model source, architecture/signing gates, no embedded macOS credentials/identity, and documentation links. A separate scan produced:

```text
PACKAGING_CREDENTIAL_SCAN_OK
```

The templates do not themselves download models or contain signing secrets. They are templates only; no Inno Setup, macOS `codesign`/`notarytool`/`stapler`, or installer execution was performed.

## 8. Secret and paid-runtime scans

A high-confidence scan over all 117 tracked files found no live Stripe key, webhook secret, or private-key block:

```text
TRACKED_HIGH_CONFIDENCE_SECRET_SCAN_OK 117 files
```

The paid root intentionally still contains its paid activation/Stripe implementation. The independent export scan found no `license_gate`, paid API URL, Stripe endpoint, secret pattern, or private key. The final `git diff --check` was clean, and the worktree was clean after the fix commit.

## Fixes made

Commit `588fcd7` contains the following minimal fixes:

1. Added the missing tracked `corrections-de.txt` resource referenced by `WhisperDictate.spec`, and added it to the community export allowlist. This fixes the observed PyInstaller `Unable to find ... corrections-de.txt` failure and prevents the generated source spec from referring to a missing resource.
2. Made the exporter's paid-comment transformation consume the complete current three-line comment instead of leaving an orphaned continuation line.
3. Hardened `release_guard.py` against model weights and Hugging Face/model-cache paths, with regression coverage.
4. Hardened `release_manifest.py` to require an HTTPS download base URL without embedded credentials, with regression coverage.
5. Added focused tests for the missing resource, export output, manifest URL safety, and model-weight guard behavior.

An intermediate export attempt correctly failed closed while the comment-transform regex was being corrected; the final fresh export and all final test runs passed.

## Remaining release blockers

These are release-publication gates, not unresolved unit-test failures:

1. **Public source/mirror/canonical host — BLOCKED.** Select and verify the public `whisper-dictate-community` repository, canonical GitHub Releases host, and model mirror/object-storage policy. The checked-in site manifest is intentionally a placeholder and the bundled config has no mirror URL.
2. **Legal/license review — BLOCKED.** The generated MIT text is intentionally first-party-only. The owner must confirm relicensing permission for every included first-party file and complete dependency, sound, and model-license/SBOM review.
3. **Windows Authenticode — BLOCKED.** No certificate, hardware key, timestamp service, or protected release environment was used. Sign the final extracted payload, then re-run the guard and regenerate hashes/manifests.
4. **macOS Developer ID/notarization — BLOCKED.** No Apple identity or notarytool profile was available. Run the template on an Apple Silicon Mac, sign inside-out, notarize, staple, Gatekeeper-validate, and hash the final artifact.
5. **Real package build/clean-machine acceptance — BLOCKED.** The local environment lacks PyInstaller in the specified venv; the global diagnostic build hit Windows path-length limits. CI with Python 3.12.x and locked/resolved dependencies still needs a real archive, smoke test, and clean-machine run.
6. **SBOM and dependency lock evidence — BLOCKED.** The repository has range-based requirements and no generated release SBOM/resolved-version report. `rapidfuzz` is declared for release builds but is called out as not installed in the current third-party notice; reconcile this before publication.
7. **Vercel deployment — BLOCKED.** The static site validates, but no Vercel project/deployment, canonical release manifest, or real artifact URLs/checksums were supplied. Keep downloads disabled until those are populated and verified.
8. **Workflow supply-chain review — BLOCKED for public release.** The workflow correctly avoids signing secrets and scopes permissions, but its GitHub/softprops actions use mutable version tags rather than immutable commit SHAs. Pin and review action revisions before relying on the workflow for a public release.

Until these gates are complete and recorded, the generated community source export is verified, but no binary or public website release should be advertised.

## Post-verification updates — 2026-09-25

After the independent report, the following additional fixes and external setup
were completed:

- The Hugging Face downloader now uses the correct
  `/{model_id}/resolve/{revision}/{filename}` URL form. Regression tests cover
  the exact URL.
- The frozen `launcher.py` now dispatches `--doctor` to `run_doctor()` instead
  of entering the normal tray/audio loop. A frozen offline doctor smoke test
  completed without starting model inference; the only expected failures were
  the two absent multi-gigabyte model caches.
- A clean short-path Windows PyInstaller build completed. The resulting
  366,226,459-byte unsigned ZIP passed the release guard and checksum/manifest
  generation. `Get-AuthenticodeSignature` reports `NotSigned`; it was not
  published.
- Public source repository created:
  `https://github.com/rorshopping/whisper-dictate-community`.
- Public static website repository created:
  `https://github.com/rorshopping/whisper-dictate-community-web`.
- Vercel production site deployed at:
  `https://whisper-dictate-community-web.vercel.app`.
- The site intentionally still has disabled artifact buttons because no
  signed stable release has been published.
- Release workflow cleanup now removes only `__pycache__`, `.pyc`, and `.pyo`
  files; the first overly broad local cleanup command was discarded and never
  published.
- Public CI/release workflow actions were pinned to reviewed commit SHAs.

The remaining blockers are now external release gates: signing/notarization,
a real model mirror/object-storage policy, legal/SBOM review, clean-machine
qualification, a real GitHub Actions release run, and publication of a final
artifact manifest. The Vercel GitHub App connection also needs to be enabled
in the Vercel dashboard; current production deployment was performed through
the authenticated CLI.

## Release execution update — 2026-09-25

The external release gates were completed for a clearly labeled **community
preview**; this supersedes the earlier "blocked" status above for the first
preview, but not the remaining qualification items.

- macOS Apple Silicon build: 105 tests passed on the Mac; the app passed the
  release guard and arm64 check. Developer ID signing used the explicit Mac
  identity, and Apple notarization submission
  `3bff589b-3bdd-4d44-ae5c-78dda3354525` was accepted. Stapling,
  `codesign --verify --deep --strict`, Gatekeeper, ZIP extraction, and the
  release guard all passed.
- The published macOS ZIP is
  `WhisperDictate-0.1.0-macos-arm64-notarized.zip`, 329,337,312 bytes,
  SHA-256 `6dcfd2ca1a270cd893094a62fa09f9f49ad7f8ed2a693164b5f7322b873c87b2`.
  AppleDouble/resource-fork metadata was removed from the final archive and the
  packaging script/test were fixed accordingly.
- Windows x64 portable ZIP:
  `WhisperDictate-0.1.0-windows-x64-unsigned.zip`, 366,226,459 bytes,
  SHA-256 `cb2a514d0456e485ca539fbaf31100188b851dda8898ee8bf330bf561d1d9e6c`.
  It is explicitly labeled an unsigned preview; no Authenticode certificate is
  being claimed.
- Public prerelease:
  `https://github.com/rorshopping/whisper-dictate-community/releases/tag/community-v0.1.0`.
  It contains both ZIPs, `release-manifest.json`, and `SHA256SUMS`.
- The Vercel production manifest was updated and deployed at
  `https://whisper-dictate-community-web.vercel.app`; the live manifest,
  GitHub asset URLs, and published metadata were checked after deployment.
- Installers, Windows Authenticode signing, a project-controlled model mirror,
  final legal/SBOM review, and clean-machine microphone/model-load acceptance
  remain future work. Model weights are still acquired on first use and are not
  bundled in either artifact.

## Portable package, license/SBOM evidence, and legacy channel update - 2026-09-25

This section records the work completed after the `community-v0.1.0` preview
publication. It does not change the preview status of the release.

### Published Windows portable package

- `WhisperDictate-0.1.0-windows-x64-portable-unsigned.zip`,
  366,227,489 bytes, SHA-256
  `f06a9ecb40f0324fbb37d438929e5c3085711c87884bf050fe133fd794c14531`, is
  published on the same prerelease. It is the verified Windows payload plus
  `WhisperDictate-Portable.cmd` and `PORTABLE.txt`; the launcher passes
  `--portable` so configuration, logs, history and the model cache stay beside
  the executable. The original `WhisperDictate-0.1.0-windows-x64-unsigned.zip`
  was retained rather than replaced.
- `release-manifest.json` and `SHA256SUMS` were regenerated for the three
  published binaries and re-uploaded; the website manifest and
  `scripts/check_release_sync.py` confirm the site advertises exactly what the
  release carries.
- Public source gained `packaging/windows/PORTABLE.txt`,
  `packaging/windows/WhisperDictate-Portable.cmd`, packaging documentation, and
  regression tests (`0f0870e`).

### Clean-extract acceptance of the portable package

The published ZIP was extracted into an empty directory and started with
`WhisperDictate.exe --portable --doctor --console` while `APPDATA`/`LOCALAPPDATA`
were pointed at an empty directory:

- 17 of 19 doctor checks passed. The only failures were the two model caches,
  which is expected on a machine that has never downloaded the ~2.4 GB
  checkpoints.
- `PortableData/config.json` was created next to the executable, the config
  parsed (27 top-level keys), microphone access enumerated 10 input devices,
  hotkey conflicts: none, clipboard access OK, and the data folder was writable.
- No application data was written to the pristine `APPDATA`; the only entry was
  the CUDA/NVML driver's own `NVIDIA` cache folder.
- The frozen app reports `torch 2.14.0+cpu` with CUDA unavailable. The Windows
  preview is therefore a **CPU-only** build; the website and release notes now
  state this instead of implying NVIDIA GPU acceleration, and a site test fails
  if that wording regresses.

### License notices and SBOM

- `THIRD-PARTY-NOTICES.md` no longer claims `rapidfuzz` is absent. It is
  declared in `requirements-release.txt`, ships in both archives as compiled
  modules, and its MIT text (Copyright 2020-present Max Bachmann, 2011 Adam
  Cohen) is now reproduced in full. Entries are labelled *env* (build
  environment) or *artifact* (verified in the published archive), and a test
  fails the build if a declared release dependency has no notice.
- New `scripts/sbom_from_package.py` generates a CycloneDX 1.5 inventory from
  the artifact itself using only the standard library, reading the
  `*.dist-info/METADATA` that PyInstaller preserved. It reports packages
  bundled without metadata as explicitly unresolved rather than dropping them.
- `sbom-windows-x64.cdx.json` and `sbom-macos-arm64.cdx.json` are attached to
  the prerelease. Each resolves 21 components with the license expression the
  wheel declared and embeds the SHA-256 of the archive it describes. Both report
  `ctranslate2` and `rapidfuzz` as unresolved. Neither archive contains a CUDA
  runtime, which is now recorded in the notices as build-environment-only
  provenance.
- The release workflow now builds the portable Windows archive (copying the
  launcher and instructions, and asserting both are present in the ZIP) and
  generates an SBOM per platform.

### Legacy channel kept online

The older Becker Hub site was **not** deleted or redirected. `becker-hub-web`
(`/whisper-dictate`) now carries a banner naming the community edition as the
canonical free channel and linking both the community site and the preview
release. The change is commit `f790a91` in `rorshopping/becker-codehub`; the
Vercel production build succeeded and the live page shows the banner.

### Still outstanding

- Windows Authenticode signing (no certificate; Windows stays explicitly
  unsigned) and signed installers. Inno Setup is not installed on this machine,
  so the Windows installer template cannot even be compiled here yet, and an
  unsigned installer would be a worse experience than the portable ZIP.
- A macOS disk image. `packaging/macos/build_signed_dmg.sh FORMAT=dmg` is
  complete and tested for syntax, but the Apple notarytool credential used for
  the 0.1.0 notarization is no longer present on the Mac (no keychain profile
  and no `AuthKey*.p8`), and a new App Store Connect API key must not be minted
  without the owner asking for it. The app itself is still signed, notarized,
  and stapled, so a DMG can be produced as soon as a credential is provided.
- A project-controlled model mirror. The model licenses (NVIDIA Open Model
  License, OpenMDW-1.1) must be reviewed for redistribution rights before any
  bucket is provisioned; first use still resolves through the pinned Hugging
  Face URLs.
- Full clean-machine acceptance with a real microphone recording and a
  completed first-use model download for both language profiles, plus the
  equivalent macOS run.
- Legal review of the notices by someone accountable for it; the SBOM covers
  package inventory, not legal opinion.
- Vercel GitHub App synchronization for the community site (production is
  deployed with the authenticated CLI).