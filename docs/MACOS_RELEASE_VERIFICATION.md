# macOS 1.1.0 artifact verification

Verified 2026-09-17 after rebuilding with history fix `d2a95da`.

- Artifact: `dist/WhisperDictate-1.1.0-macos-arm64.zip`
- SHA-256: `a84368d7dbca12d993dfba6a9b2616b5a494643d04789527fb7ea86a31f7e15e`
- Signer: Developer ID Application, team `AGYVQ59A5S`, G2 intermediate
- Apple notarization submission: `a2f0efdf-bd77-4e3b-a91d-136c0b627647` — **Accepted**
- `codesign --verify --deep --strict`: passed
- `xcrun stapler validate`: passed
- `spctl --assess --type execute`: accepted, source `Notarized Developer ID`
- Isolated-home doctor with bundled defaults and copied model cache: **21/21 passed**
- Frozen EN model preload: passed on MPS (float16)
- Embedded `history_store`, `enhanced_features`, and `main` code objects: match current source
- Fresh extraction of the ZIP: signature, stapled ticket, Gatekeeper and isolated doctor all passed (21/21)

These checks establish signing, notarization, artifact integrity, dependency
availability, and cached default-model startup. They do not establish a complete
microphone-to-cursor test on a fresh user account, offline DE transcription, or
compatibility with every macOS version or target application. No public upload
was performed as part of these checks.

Build command: `bash scripts/build_release.sh --sign --notarize --zip`.
Notary credentials are stored in Keychain profile `whisper-dictate`; keys and
certificates must remain outside the repository.
