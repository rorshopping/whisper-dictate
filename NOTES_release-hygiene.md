# Release hygiene and publishing gate

This runbook covers the release checks added around the PyInstaller packages.
It is intentionally usable without credentials: the CI jobs build and inspect
**unsigned qualification artifacts** and create a draft only.  Signing,
notarization, and the final publish decision are operator gates and must never
be smuggled into a pull request or committed as secret material.

The release workflow is in [`.github/workflows/release.yml`](.github/workflows/release.yml).
The two dependency-free helpers are:

- [`scripts/release_guard.py`](scripts/release_guard.py) — checks archive or
  package member names before an artifact is uploaded.
- [`scripts/release_manifest.py`](scripts/release_manifest.py) — hashes final
  assets and writes `release-manifest.json` plus `SHA256SUMS`.

## Non-negotiable release invariants

1. Build from a clean checkout of the exact tag being released.  Do not build
   from an uncommitted worktree, a downloaded source archive, or a machine's
   existing virtualenv.
2. Use Python **3.12.x** for both CI build jobs.  Record the exact patch
   version in the release notes.  Python 3.13+ is not a substitute for the
   release qualification build.
3. Install from the declared dependency files, never from a hand-copied list:
   `requirements.txt` is the runtime source of truth and
   `requirements-release.txt` adds the build-only tools.
4. Run the guard on the **final** archive after signing and notarization.
   Signing, stapling, and re-archiving change bytes; hashes from an unsigned
   archive must not be copied to a signed release.
5. Keep the draft private until every gate in this document is green.  The
   workflow's final job is the only job with `contents: write`; it attaches
   files to a draft and does not publish them.

## 1. Pin and review the build environment

The current dependency declarations intentionally describe supported ranges;
they are not a claim that every release used the newest package.  Before a
release, the release operator must create a reproducibility record (or an
approved lock/constraints file) from the clean build environment:

```text
Python: 3.12.x (exact patch recorded)
Runtime dependencies: requirements.txt
Build dependencies: requirements-release.txt
Platform markers: Windows CUDA packages and macOS package set recorded
```

Do not silently upgrade a dependency in a release branch.  For each candidate,
review the resolved versions, wheel/source hashes where available, native
ABI compatibility, and the `THIRD-PARTY-NOTICES.md` update.  Keep the lock or
resolved-version report with the release evidence.  A future dependency change
should update the declaration in a reviewed change, not just the CI runner.

The local dry-run checks are:

```bash
python -m pip install -r requirements-release.txt
python -m pip check
python -m unittest discover -s tests -p "test_*.py" -v
```

These commands may download packages when run on a new machine.  They are
for an explicitly provisioned build environment; no credentials are needed
for the tests or guard.

## 2. Build and inspect each artifact

The workflow runs tests, checks dependency consistency, builds with
`WhisperDictate.spec`, creates a platform archive, and runs the guard before
uploading it as a workflow artifact.  The equivalent local checks for an
already-built archive are:

```bash
python scripts/release_guard.py path/to/WhisperDictate-v1.2.3-windows-x64.zip
python scripts/release_guard.py path/to/WhisperDictate-v1.2.3-macos-arm64.zip
```

The guard is deterministic and dependency-free.  It fails closed for unsafe
archive paths and for names associated with:

- application logs (`dictate.log`, `*.log`) and transcription history
  (`transcription-history.jsonl` and other `*.jsonl` data);
- local overrides (`config.local.json`, `*.local.*`) and environment files
  (`.env`, `.env.*`, `.envrc`);
- `lost_audio`/recording debris, virtual environments, Python caches, VCS and
  editor state, dependency/build caches, temporary/backup files; and
- likely credential or signing material (`.pem`, `.key`, `.p12`, `.pfx`, and
  similar files), except a narrowly allowlisted public CA bundle such as
  `cacert.pem`.

The rule is based on member names, not file contents.  If a new private or
generated file type can enter a package, add a narrowly scoped rule and a
regression test in `tests/test_release_hygiene.py`; do not weaken the guard to
make a particular build pass.

## 3. Architecture qualification

### Windows

The Windows job must run on an x64 runner.  Check both the runner and the
built executable before labeling the asset `windows-x64`:

```powershell
python -c "import platform; print(platform.machine())"
(Get-Item .\dist\WhisperDictate\WhisperDictate.exe).VersionInfo.FileVersion
```

The executable must be a 64-bit Windows image and the archive name must match
the verified architecture.  Do not silently publish an ARM or 32-bit build
under the x64 name.

### macOS

The release asset is explicitly `macos-arm64`; the workflow uses an arm64
runner and fails if the runner reports another architecture.  On the build
machine, verify both the host and the Mach-O images:

```bash
uname -m
file dist/WhisperDictate.app/Contents/MacOS/WhisperDictate
lipo -info dist/WhisperDictate.app/Contents/MacOS/WhisperDictate
```

If Intel support is added, make it a separately named build (for example,
`macos-x64`) and qualify it independently.  Never relabel an Intel artifact
as arm64 or combine architectures without repeating the full gate.

## 4. Signing and notarization (required release inputs)

The CI workflow intentionally has **no signing step and no secret references**.
A draft assembled by CI is not publishable until an authorized operator
provides the following inputs through the organization's protected release
environment:

### Windows Authenticode

- An approved code-signing certificate and hardware-backed key (or the
  organization's documented signing service).
- A timestamp service configured for the certificate.
- The final extracted Windows directory must be signed after all application
  resources are in place and before the final ZIP is made.

Verify the result and retain the signing certificate thumbprint, timestamp,
and verification output as release evidence:

```powershell
Get-AuthenticodeSignature .\WhisperDictate.exe
# The status must be Valid and the timestamp must be present.
```

Do not place a certificate, password, token, or cloud-signing credential in
this repository, an artifact, a workflow log, or the manifest.

### macOS Developer ID and notarization

- An approved Apple Developer ID Application identity.
- The required hardened-runtime options and the microphone/automation
  entitlements used by the app.
- Apple notarization credentials supplied at execution time (for example, a
  `notarytool` key/profile managed outside the repository).  The issuer/key
  material is an input, not a value to invent in YAML.

Sign nested code inside-out, sign the final app bundle, submit the archive,
staple the ticket, and validate the result before making the public ZIP:

```bash
codesign --verify --deep --strict dist/WhisperDictate.app
xcrun stapler validate dist/WhisperDictate.app
spctl --assess --type execute --verbose=4 dist/WhisperDictate.app
```

The existing `scripts/notarize_macos_*.sh` files are operator tooling for a
credentialed Mac session; they are not invoked by the unsigned CI gate.  Review
their inputs and run them only in the protected release environment.

## 5. Checksums and the Vercel download manifest

Hash **after** the final signing/stapling step and after the final archive is
created.  Generate the aggregate metadata with:

```bash
python scripts/release_manifest.py \
  WhisperDictate-v1.2.3-windows-x64.zip \
  WhisperDictate-v1.2.3-macos-arm64.zip \
  --release v1.2.3 \
  --download-base-url "https://github.com/ORG/whisper-dictate/releases/download/v1.2.3" \
  --output release-manifest.json \
  --checksums SHA256SUMS
```

`release-manifest.json` has schema
`whisper-dictate.release-manifest.v1` and contains sorted asset entries with
`name`, `url`, `sha256`, `size_bytes`, `platform`, and `architecture`.  A
Vercel download page can fetch the JSON and render one download link per entry;
it should not need to parse log text or the GitHub HTML page.  The manifest is
deterministic and has no timestamp, but it is still release evidence and must
be regenerated if an asset changes.

`SHA256SUMS` uses the conventional `<digest>  <filename>` format.  Verify it
on both build platforms before attaching the files:

```bash
shasum -a 256 -c SHA256SUMS                 # macOS/Linux
Get-FileHash -Algorithm SHA256 <asset>      # Windows PowerShell
```

Attach the final archives, `SHA256SUMS`, the aggregate `release-manifest.json`,
and the platform-specific manifests.  Do not hash a manifest and then include
that manifest in its own input set.

## 6. SBOM and license report

Before approval, generate an SBOM from the exact, clean build environment
(for example, a CycloneDX or SPDX report from the resolved dependency set) and
store it with the release evidence.  The report must identify the Python
version, platform, direct/transitive packages, and native wheels where they
can affect the binary.

Also review and attach/update:

- `THIRD-PARTY-NOTICES.md` for redistributed packages and other bundled
  third-party material;
- the licenses for the PyInstaller bootloader/bundled runtime components;
- the model-license notices and model download terms; and
- any signing/notarization notices required by the distribution channel.

An SBOM generator and a license-report tool are release tooling, not runtime
application dependencies.  Pin their versions in the release environment and
record their output; do not install unreviewed tools as a side effect of the
application installer.

## 7. Clean-machine qualification

Use a fresh user profile or disposable Windows 10/11 x64 and macOS 13+
machine, with no source checkout, old virtualenv, existing app config, or
cached audio available:

1. Verify the archive name, SHA-256, and signature/notarization before
   extraction.
2. Extract to a new directory and run the packaged executable/app, not
   `main.py` or `launcher.py` from source.
3. Confirm first-run model download behavior, microphone permission, hotkeys,
   clipboard/paste behavior, and both configured language profiles.
4. Run again with networking disabled after models are cached and confirm the
   app still behaves as documented.
5. Search the extracted package for logs, history, `.env`, local config, audio,
   credentials, and virtualenv directories.  The archive guard should make this
   unnecessary, but a clean-machine check catches packaging mistakes.
6. Remove the machine and its profile after recording pass/fail evidence;
   never copy a user's config, history, or audio into release evidence.

## 8. Final approval checklist

- [ ] Clean exact tag, Python 3.12.x patch recorded, dependency resolution and
      `pip check` recorded.
- [ ] Existing unit tests and the new release-hygiene tests pass on both
      build platforms.
- [ ] Windows and macOS architecture labels match verified binaries.
- [ ] Windows Authenticode signature and timestamp are valid.
- [ ] macOS Developer ID signature, hardened runtime, notarization, and staple
      validation pass.
- [ ] Guard passes on the final archives; no private/generated files are
      present.
- [ ] `SHA256SUMS` verifies on both platforms and the aggregate manifest points
      to the final, signed assets.
- [ ] SBOM, third-party/license report, and model-license review are attached.
- [ ] Clean-machine qualification is complete and evidence is retained.
- [ ] A human reviews the draft and explicitly approves publication.

Until every box is checked, leave the GitHub release as a draft.  Do not upload
credentials, signing files, local configs, logs, history, or a virtualenv to
make a release job pass.
