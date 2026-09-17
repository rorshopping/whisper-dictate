# Launch checklist — blocked

Current status: **untrusted previews only; not ready for public launch**.
Historical local checks do not establish that a downloaded package is trusted
or works on a clean machine. No release is authorized by this checklist.

## 1. Artifact and trust gates

| Platform | Current status | Required before public release |
|---|---|---|
| macOS arm64 | Untrusted preview exists; Developer ID credentials missing | Developer ID signing, notarization/stapling, normal Gatekeeper acceptance, clean-machine functional tests |
| Windows x64 | Untrusted unsigned preview exists; trusted signing credentials missing | Trusted Authenticode signing/timestamp, signature validation, clean-machine functional tests |
| Linux x86_64 | No artifact available | Build, define supported distributions/display sessions, test the exact packaged artifact |

For every offered platform:

- [ ] Audit bundled defaults and package contents for personal data and secrets.
- [ ] Test launch, microphone permission, model setup, hotkeys, transcription,
      insertion at cursor, settings, history, and restart on a clean machine.
- [ ] Verify trust using the platform's normal controls; do not bypass security
      warnings to count a release gate as passed.
- [ ] Record model/network requirements, hardware support, and known limitations.
- [ ] Generate and verify checksums for the exact approved artifacts. Checksums
      alone do not prove publisher trust.

## 2. Stage drafts only

`scripts/publish_release.sh` creates draft prereleases, refuses existing public
releases, stops on HTTP/API errors, and never deletes or replaces assets.
Specify actual artifact paths rather than globs for platforms that do not exist.
See `docs/RELEASE.md` for the staging command and failure behavior.

- [ ] Keep unapproved artifacts in drafts. Do not promote during uploads.
- [ ] Inspect the complete asset list and release notes before approval.
- [ ] Obtain explicit public-release approval only after the gates above pass.

Staging is not publication. Drafts are not anonymously downloadable, and the
publisher deliberately does not check anonymous download URLs or update the site.

## 3. Website and public-access gates

- [ ] Describe actual release status; do not offer a stable download backed only
      by an untrusted preview.
- [ ] Do not show a Linux download until a validated artifact exists.
- [ ] Check all platform/architecture, signing, offline, and performance claims
      against the exact approved artifacts.
- [ ] After separately approved publication, verify each offered download
      anonymously, following redirects; validate its checksum and normal launch.
- [ ] Confirm stale feeds/caches do not resurrect unavailable or untrusted links.

## 4. Launch copy

`docs/LAUNCH_TWEETS.md` is marked **NOT READY TO POST** and documents withdrawn
claims. No launch thread or stable-release announcement is currently approved.

- [ ] Finish artifact, trust, website, and public-access gates first.
- [ ] Check factual claims independently of approximate tweet-length checks.
- [ ] Do not claim public source access: the source repository is private.
- [ ] Avoid unverified competitor prices, privacy absolutes, GPU/performance
      guarantees, or unsupported platform availability.
