# Releasing Whisper Dictate

**Current status: pre-release, not approved for public distribution.** Only
untrusted macOS and Windows previews exist. There is no Linux artifact yet;
required macOS and Windows signing credentials are missing.

The intended packaging uses PyInstaller to bundle Python and dependencies.
Packaging success alone does not prove clean-machine functionality or trust.
**No GitHub workflows are used.** Builds are platform-native; the commands below
describe the intended release workflow, not completed release validation.

## Planned artifacts (not a list of available downloads)

| Platform | Artifact | Built on | Script |
|---|---|---|---|
| macOS | `Whisper Dictate.app` → `WhisperDictate-1.1.0-macos-arm64.zip` | a Mac | `scripts/build_release.sh` |
| Windows | `WhisperDictate-1.1.0-win64[-unsigned].zip` | a Windows machine | `scripts\build_release.ps1` |
| Linux | `WhisperDictate-1.1.0-linux-x86_64.tar.gz` | Linux (oldest supported base) | `scripts/build_release_linux.sh` |

Model weights are **not** bundled. First use requires the selected models in
the Hugging Face cache, normally obtained over the network. Download sizes vary
by model/profile. Validate cached offline operation in each exact artifact;
`HF_HUB_OFFLINE=1` alone is not a guarantee about all application network traffic.

## Release defaults are not the developer's config

`packaging/defaults/` holds the config and text files that get seeded into the
user's data folder on first run. It must contain **only** neutral templates —
never the developer's hotwords, corrections, snippets, history, or logs. The
current `corrections-en.txt` in the repo root contains personal project
vocabulary; `packaging/defaults/corrections-en.txt` is the sanitised version.
Check this every release: a leaked download is permanent.

## macOS

```bash
./scripts/build_release.sh --sign --notarize --zip
```

* **`--sign`** needs a **Developer ID Application** certificate in the keychain.
  This is a different certificate from *Apple Development* and *Apple
  Distribution*: those sign for development and for the App Store, and neither
  makes Gatekeeper accept a website download. A Developer ID certificate can
  only be created in the Apple Developer portal by an account admin
  (Xcode → Settings → Accounts → Manage Certificates → **+** → *Developer ID
  Application*). `security find-identity -v -p codesigning` must list it.
* The script signs inside-out (every `.dylib`/`.so`/nested binary, then the
  bundle) with `--options runtime` and `packaging/entitlements.plist`. That
  entitlements file is not optional for a hardened build: without
  `allow-jit`/`allow-unsigned-executable-memory` torch crashes on the first
  tensor op, and without `disable-library-validation` it refuses to load
  ctranslate2's dylibs.
* **`--notarize`** submits to Apple and staples the ticket. It needs stored
  credentials:

  ```bash
  xcrun notarytool store-credentials whisper-dictate \
      --apple-id <apple-id> --team-id AGYVQ59A5S --password <app-specific-password>
  ```

  The password is an **app-specific password** from appleid.apple.com, not the
  Apple ID password. (The App Store Connect API key at
  `~/.appstoreconnect/private_keys/AuthKey_BP3N265886.p8` authenticates as an
  individual key and is currently rejected by the API; notarization does not
  need it.)
* Both flags **fail closed**: no certificate or no notarization profile means no
  artifact and no "signed release" claim.

Without flags the script produces an untrusted `.app` for local testing, not
an approved public release. Do not instruct users to bypass Gatekeeper.

## Windows

```powershell
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -Sign -Release
```

* **Windows Developer Mode is not needed.** Developer Mode is about symlinks,
  the Windows Subsystem for Linux, and sideloading development MSIX packages.
  An unpacked x64 desktop app builds and runs without it; nothing in this
  pipeline touches it.
* `-Sign` signs with the best code-signing certificate in `Cert:\CurrentUser\My`
  (or `-Thumbprint <sha1>`), timestamped via DigiCert so the signature outlives
  the certificate. The script verifies the result and classifies it:
  * **trusted** — the certificate chains to a public CA (or is in the machine's
    trusted store). This is what a release needs.
  * **self-signed** — only verifies where the certificate is installed. Useful
    for one machine, **never** for a public download.
  * **unsigned** — no trusted publisher signature; not approved for public
    distribution. Do not instruct users to bypass SmartScreen.
* `-Release` refuses to build unless the signature is trusted, and prints the
  three real options (OV/EV certificate, Azure Trusted Signing, or an explicitly
  labelled unsigned preview).
* Building on a machine without the certificate is fine — omit `-Sign` and the
  zip is named `...-win64-unsigned.zip` so the website never implies otherwise.

## Linux

```bash
./scripts/build_release_linux.sh --tar          # tarball, the primary artifact
./scripts/build_release_linux.sh --tar --appimage
```

* Build on the **oldest** distribution you support: a frozen bundle links the
  build machine's glibc.
* The script checks for the host libraries PyInstaller cannot bundle
  (PortAudio, X11/xcb, xkbcommon, ALSA/PulseAudio) and prints what is missing.
* **X11 is the supported session.** Recording works under PipeWire/PulseAudio,
  but `pynput`'s injection and global-hotkey backend are X11: on a Wayland
  session the paste only works through XWayland and hotkeys may not be captured.
  The download page must say this.

## Draft staging (not publishing)

`scripts/publish_release.sh` stages artifacts in the dedicated release-assets
repository `rorshopping/whisper-dictate-releases`. It has no public-publish mode.

```bash
TAG=v1.1.0-preview.1 ./scripts/publish_release.sh "dist/WhisperDictate-1.1.0-macos-arm64.zip"
```

- New releases are created with **both `--draft` and `--prerelease`**. The default
  tag remains `v1.1.0`; if that tag is already public the script refuses it. Use
  a new draft tag, not a replacement of an existing public release.
- An existing release must still be a draft before every upload. Public releases
  are refused, including public prereleases. Do not promote a draft concurrently:
  GitHub does not provide an atomic draft-check-and-upload operation.
- Existing assets are never deleted or overwritten. A filename collision fails
  the batch preflight; duplicate input basenames also fail. Paths containing
  spaces are supported. Adjacent `.sha256` files are staged automatically.
- API/network failures and non-201 upload responses stop execution. A failed
  batch can leave earlier uploads in the draft; no automatic cleanup is done.
- Draft assets are **not anonymous downloads**. Upload success is not evidence
  of signing, artifact integrity, clean-machine functionality, or public access.

Public release approval is separate and currently blocked. Complete the gates
in `docs/LAUNCH_CHECKLIST.md`, then review the exact artifacts and website claims
before any promotion. Filename labels and checksums are not proof of trust.
Do not advertise Linux until an artifact exists and has been validated.

## Verifying a build

```bash
# macOS
"dist/Whisper Dictate.app/Contents/MacOS/Whisper Dictate" --doctor
codesign --verify --deep --strict --verbose=2 "dist/Whisper Dictate.app"
spctl -a -vvv -t install "dist/Whisper Dictate.app"   # Gatekeeper's own verdict

# Windows
dist\WhisperDictate\Whisper Dictate.exe --doctor
Get-AuthenticodeSignature dist\WhisperDictate\Whisper\ Dictate.exe

# Linux
dist/WhisperDictate/Whisper\ Dictate --doctor
```

`--doctor` writes its full report to `doctor-report.txt` in the data folder
(`~/Library/Application Support/Whisper Dictate` on macOS,
`%APPDATA%\Whisper Dictate` on Windows, `~/.local/share/whisper-dictate` on
Linux) when the app has no console to print to.
