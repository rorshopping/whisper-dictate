# Community source export notes

`scripts/export_community.py` creates a deterministic source export without
changing the checked-out application. It is a release-preparation scaffold,
not a repository mirror.

## Usage

From this worktree, provide a destination outside the source checkout:

```powershell
python scripts/export_community.py ..\whisper-dictate-community
```

The destination may be absent or an existing empty directory. A nonempty
destination is refused without an explicit opt-in:

```powershell
python scripts/export_community.py ..\whisper-dictate-community --force
```

For a review fixture or a different checkout, use `--source-root`:

```powershell
python scripts/export_community.py `
    --source-root C:\path\to\fixture `
    --output C:\path\to\community-output
```

The exporter stages the complete tree beside the destination and only replaces
the destination after all files have been written and checked. It rejects a
destination equal to, above, or below the source root, follows no source
symlink, and does not use the current directory's file order. The generated
manifest is sorted by POSIX path and records byte sizes and SHA-256 hashes.

## What is selected

The exporter has an explicit exact-path allowlist in
`scripts/export_community.py`. It includes the application Python modules,
configuration/data files, tracked sound assets, launch helpers, the portable
path runtime (`app_paths.py`), its path-layer tests and notes, application
tests, `README.md`, `COMMUNITY_RELEASE_DECISION.md`, and
`THIRD-PARTY-NOTICES.md`. Internal roadmap files and remote sound-download
helpers are intentionally excluded. New files are not copied merely because
they are present in the checkout; a reviewer must add them to the allowlist.

A denylist documents defense-in-depth exclusions for the paid activation
module and test, Stripe/payment and marketing material, the existing website
and API routes, release automation (the GitHub workflow and notarization
helpers), alternate site content, secrets and
credential files, personal/local files, logs and history, virtual
environments, build/dist output, caches, and downloaded model weights. The
allowlist is the primary control, so an unlisted file is excluded even if a
future denylist misses its name.

The following are generated into every output and are not copied from the
paid source checkout:

- `LICENSE`: a standard MIT notice explicitly limited to first-party source.
- `MODEL_LICENSES.md`: pointers to the NVIDIA Open Model License and OpenMDW
  terms, with the statement that weights are downloaded separately and are not
  MIT-licensed first-party material.
- `COMMUNITY_EXPORT_MANIFEST.json`: a sorted, hash-based inventory of the
  exported payload. The manifest intentionally does not hash itself.

Generated copies of `main.py`, `config.json`, and `README.md` receive narrow,
documented transformations: the activation import/guard/notice polling and
license-only configuration are removed, and the paid README section is
replaced by a community license section. If those expected shapes cannot be
found safely, the exporter fails closed instead of publishing a partial
runtime. The source files themselves are not edited.

The portable path layer is treated as a required runtime dependency:
`app_paths.py`, `tests/test_app_paths.py`, and `NOTES_portable-paths.md` are
included in the allowlist, and the exporter fails if the generated
`main.py` loses its `import app_paths` statement. This keeps resource paths,
writable user data, and portable-mode paths together in the source export;
private data directories and `*.local.txt` files remain excluded.

The exporter, this notes file, and its maintainer test are release tooling,
not application payload, and are therefore not copied into the public tree.
Run the tests in
this checkout before producing an artifact:

```powershell
python -m unittest tests/test_community_export.py
```

## Limitations and review checklist

- This is not a legal determination that every first-party file is
  relicensable. The release owner must confirm the MIT grant and review the
  allowlist before publication.
- The MIT file does not relicense dependencies, sound samples, or model
  weights. `THIRD-PARTY-NOTICES.md` is preserved as the dependency/model
  notice record; `MODEL_LICENSES.md` is a starting pointer, not a replacement
  for the publishers' terms.
- Models are downloaded from their publishers at runtime. They are not
  vendored, verified, or redistributed by this exporter, and an offline setup
  still needs a separately obtained model cache.
- The output is source only. It does not create a remote repository, publish a
  release, build binaries, select a canonical website, or alter the paid
  application, website, release workflow, or model manager.
- Before publishing, review the generated manifest, inspect the transformed
  runtime, run the application tests on a clean machine, and separately verify
  every dependency and model license/version.
