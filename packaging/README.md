# Packaging templates

These templates package the community edition's existing PyInstaller output.
They are deliberately build inputs and release gates, not a build or signing
service. Nothing in this directory downloads a model, creates a signing
identity, or uploads credentials.

## The shared PyInstaller payload

Build the payload from the repository root with
[`WhisperDictate.spec`](../WhisperDictate.spec). The Windows build produces
`dist/WhisperDictate/` as a PyInstaller **onedir** directory; the macOS build
produces `dist/WhisperDictate.app` from the same spec. Those are the source
inputs for the templates. A release version is supplied when compiling the
Windows template, for example:

```text
ISCC.exe /DMyAppVersion=1.2.3 packaging\windows\WhisperDictate.iss
```

The `MyAppVersion` value is metadata and output naming; it does not change
the application payload. Keep the complete onedir tree together. Do not add a
`models`, Hugging Face cache, `.safetensors`, `.gguf`, or other model-weight
file to the payload. Model acquisition is a first-run operation, not an
installer operation.

The portable artifacts are a ZIP of the Windows onedir directory and a
preserved `.app` ZIP (or DMG) made from the macOS app. They contain the same
frozen application payload as the installers. A portable artifact does not
create an uninstaller; the Windows installer adds only the per-user
installation/shortcut/uninstaller wrapper around the identical payload.

## Windows installer

[`windows/WhisperDictate.iss`](windows/WhisperDictate.iss) is an Inno Setup
6 template. Its required input is the complete
`dist/WhisperDictate/` directory (including the executable and `_internal`
files), plus `icon.ico` and `LICENSE` from the repository. It defaults to a
non-elevated per-user directory under `%LOCALAPPDATA%\Programs`, never
selects a Program Files location, and creates optional Start Menu and desktop
shortcuts. `UsePreviousAppDir=no` prevents a prior machine-wide path from being
inherited. `Uninstallable=yes` enables the generated uninstaller. Runtime
configuration, logs, history, and model caches stay with the per-user
installation/cache rather than being staged into a machine-wide directory.

The template deliberately does not download, unpack, or install a model. The
application remains responsible for obtaining a model on first run. Review
the payload and run the Windows package denylist and clean-machine checks
before publishing it. Code signing of the installer or executable is a
separate release gate; this template contains no certificate, private key,
or signing command that would guess an identity.

## macOS signed artifact

[`macos/build_signed_dmg.sh`](macos/build_signed_dmg.sh) packages the same
`dist/WhisperDictate.app` after checking that the host and executable are
Apple Silicon (`arm64`). Set `FORMAT=zip` for a notarized, stapled `.app` zip
(the default), or `FORMAT=dmg` for a signed/notarized/stapled disk image.
The checked-in [`macos/entitlements.plist`](macos/entitlements.plist) is the
runtime entitlement input; it contains no credentials.

The script is a gated template, not a way to sign unsigned output. Before
running it, the release operator must provide all of the following:

- an installed, explicitly selected `Developer ID Application: ...` identity
  in `DEVELOPER_ID_APPLICATION`;
- a separately configured `xcrun notarytool` keychain profile named by
  `NOTARYTOOL_PROFILE` (credentials are managed outside this repository);
- Apple Silicon macOS, Xcode command-line tools, `codesign`, `notarytool`,
  `stapler`, `spctl`, `ditto`, and (for DMG output) `hdiutil`;
- a complete `dist/WhisperDictate.app` and the entitlements file.

The script never selects a default identity, stores a private key, or embeds
an Apple ID, team secret, issuer ID, key ID, or password. It must complete
signature verification, notarization, stapling, and Gatekeeper assessment
before writing the release artifact. A local zip produced before those gates
must not be published.

## Release checklist

1. Build and inspect the PyInstaller onedir/app payload; verify the model
   denylist and record its version and SHA-256.
2. Build the portable archive or run the platform template against that same
   payload.
3. On Windows, verify the generated per-user installer, shortcuts, and
   uninstaller. Apply the separate Windows signing gate if required by the
   release channel.
4. On macOS, satisfy the Developer ID, notarization, stapling, and Gatekeeper
   gates above; do not substitute an unsigned zip.
5. Run the lightweight packaging tests without Inno Setup, macOS, Docker, or
   network access:

   ```text
   python -m unittest discover -s tests -p "test_packaging.py"
   ```

See [`../COMMUNITY_RELEASE_DECISION.md`](../COMMUNITY_RELEASE_DECISION.md)
for the community distribution and model-handling decisions. The application
source and root README remain the source-of-truth documentation; this file
only describes packaging inputs and gates.
