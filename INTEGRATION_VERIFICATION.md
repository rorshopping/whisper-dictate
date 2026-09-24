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
