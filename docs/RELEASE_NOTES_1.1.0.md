# Whisper Dictate 1.1.0 — pre-release, not ready for public distribution

**Status: untrusted previews only.** macOS and Windows preview artifacts exist,
but they are not approved production releases. No Linux artifact is available.
Required signing credentials are missing. Do not publish these previews as a
stable release or instruct users to bypass operating-system security checks.

## Artifact status

| Platform | Preview artifact | Release status |
|---|---|---|
| macOS (Apple Silicon) | `WhisperDictate-1.1.0-macos-arm64.zip` | Untrusted preview; Developer ID signing and notarization outstanding |
| Windows (x64) | `WhisperDictate-1.1.0-win64-unsigned.zip` | Untrusted, unsigned preview; trusted Authenticode signing outstanding |
| Linux (x86_64) | None | Not built or validated for release |

An ad-hoc or locally verified signature is not equivalent to a trusted publisher
signature. A `.sha256` file can detect changed bytes when compared with a trusted
reference; it does not establish the publisher's identity or that an application
is safe. This document is not evidence that an artifact has passed validation.

## Preview scope

Whisper Dictate is intended to provide local push-to-talk transcription and
insertion at the cursor. The source includes packaging support, per-user data
storage, settings and transcription-history windows, hotword corrections, voice
snippets, and optional English/German spoken punctuation. Their presence in the
source does not establish end-to-end functionality in each packaged artifact.

The standalone packaging aims to include Python and application dependencies.
Model weights are not bundled and must be obtained separately on first use.
Initial setup therefore requires network access unless the required models have
already been cached. Model download sizes and CPU/GPU performance vary by model,
profile, and machine; no cross-platform performance claim is made here.

The packaged application's intended data locations are:

| Platform | Folder |
|---|---|
| Windows | `%APPDATA%\Whisper Dictate` |
| macOS | `~/Library/Application Support/Whisper Dictate` |
| Linux (planned package) | `~/.local/share/whisper-dictate` |

Configuration, logs, and transcription history may contain sensitive text.
Local processing is not a guarantee that the computer, its backups, or its
stored data are secure. Offline behavior and network activity must be checked
against the exact release artifact before making absolute privacy claims.

## Outstanding release gates

- Obtain a macOS Developer ID Application identity, sign the complete bundle,
  notarize and staple it, and verify normal Gatekeeper acceptance.
- Obtain trusted Windows Authenticode signing credentials, sign and timestamp
  the executable, and validate the downloaded package on a clean machine.
- Build a Linux artifact and document/test its supported distribution and
  display-session requirements. X11-based input support in the source is not
  evidence of a working Linux release; Wayland compatibility is unverified.
- Record clean-machine results for launch, microphone access, model setup,
  dictation, hotkeys, text insertion, and data handling for each offered platform.
- Audit bundled defaults and contents for private data; generate and verify
  checksums for the exact approved artifacts.
- Review download-page and launch-copy claims against that evidence before any
  public release or promotion.

`scripts/publish_release.sh` only stages assets in a draft prerelease, refuses
existing public releases, and never replaces existing assets. Staging does not
satisfy any of the trust or validation gates above. See `docs/RELEASE.md` for the
operator workflow.
