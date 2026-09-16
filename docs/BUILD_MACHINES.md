# How the three builds work (and what needs to be true on each machine)

Whisper Dictate ships as three independent standalone builds, produced on three
different machines. There is no GitHub workflow by design: the macOS build must
run where the Developer ID key lives, the Windows build must run on Windows (and
may need a certificate that cannot be copied around), and the Linux build must
run on the oldest glibc you support.

This file is the operator's view. `docs/RELEASE.md` is the reference for the
scripts and their flags.

## Why the builds are not cross-compiled

| Platform | Why it must build there |
|---|---|
| macOS | codesign only signs Mach-O, and notarization is Apple's service. Bundling is also arch-specific (`arm64` today). |
| Windows | PyInstaller freezes a Windows PE binary; Authenticode signing needs the certificate's private key, which for an HSM/EV certificate never leaves the token. |
| Linux | A frozen bundle links the build host's glibc. Built on Ubuntu 24.04 it will not start on 22.04, so build on the oldest base you support. |

## Certificate status (2026-09-16)

* **macOS: no `Developer ID Application` identity.** The keychain has Apple
  Development (team XJJBC8TUNW) and Apple Distribution (team AGYVQ59A5S).
  Neither is accepted by Gatekeeper for a website download. A Developer ID
  certificate is created in the Apple Developer portal by an account admin:
  Xcode → Settings → Accounts → Manage Certificates → **+** → *Developer ID
  Application*. Until then every macOS artifact is an unsigned preview and the
  release notes say so.
* **Windows: no code-signing certificate.** `Cert:\CurrentUser\My` is empty of
  `-CodeSigningCert` entries. Without a trusted certificate the executable is
  unsigned and SmartScreen warns on first launch. Windows **Developer Mode is
  not needed and does not help** — it is for symlinks and sideloaded
  development MSIX packages, not for an unpacked desktop app.

Both gaps are shown to the user instead of hidden: the download page labels an
unsigned artifact "Unsigned preview", and `scripts/build_release.ps1 -Release`
refuses to produce a zip whose signature is not trusted.

## Build commands

```bash
# macOS (this Mac) — unsigned preview that anyone can still run
./scripts/build_release.sh --zip
# macOS, once a Developer ID identity exists
./scripts/build_release.sh --sign --notarize --zip

# Windows (over SSH; see below)
ssh beckerhub-pc-tail "powershell -NoProfile -ExecutionPolicy Bypass -File C:\\Users\\Richard\\win_build.ps1"
# or, in the repository checkout on that machine:
powershell -ExecutionPolicy Bypass -File scripts\build_release.ps1 -Sign

# Linux (x86_64 VM on this Mac, or any x86_64 Linux box)
limactl shell wdlinux -- ./scripts/build_release_linux.sh --tar
```

## The Windows machine

* Reached at `beckerhub-pc-tail` (Tailscale) or `beckerhub-pc` (LAN). It is a
  normal desktop: it sleeps, so a timed-out SSH is not a broken build.
* It has Python 3.14 and 3.12, 31 GB RAM, ~96 GB free.
* **Its git checkout cannot authenticate to GitHub** (no credential helper), so
  the build sources are copied over instead of pulled:

  ```bash
  tar --exclude='.venv' --exclude='dist' --exclude='build' --exclude='.git' \
      --exclude='__pycache__' --exclude='dictate.log*' -czf /tmp/whisper-src.tar.gz .
  scp /tmp/whisper-src.tar.gz beckerhub-pc-tail:"C:/Users/Richard/whisper-src.tar.gz"
  ssh beckerhub-pc-tail "powershell -NoProfile -Command \"tar -xzf C:\\Users\\Richard\\whisper-src.tar.gz -C C:\\Users\\Richard\\whisper-build\""
  ```

  (`C:\Users\Richard\Documents\Projects\whisper-dictate` is the user's own
  checkout and is left alone; the build uses `C:\Users\Richard\whisper-build`.)
* `win_build.ps1` creates a **fresh CPU-only venv** at
  `C:\Users\Richard\whisper-venv`. The developer venv on that machine has
  `torch+cu126` (4 GB) plus the NVIDIA CUDA runtime (2 GB), which would push the
  download past 5 GB for no benefit: the Nemotron models are 0.6B parameters and
  run fine on the CPU. GPU users can install the CUDA wheel afterwards.
* The unit tests run on Windows before freezing, so a platform-specific break is
  caught before an hour of packaging.

## The Linux VM

`limactl start wdlinux` boots a Debian 12 x86_64 VM (QEMU, 4 CPU / 8 GB) defined
by `packaging/lima-linux-build.yaml`. Build inside it rather than on the host so
the artifact links Debian 12's glibc, not macOS's.

```bash
limactl shell wdlinux -- sudo apt-get update
limactl shell wdlinux -- sudo apt-get install -y python3-venv python3-pip \
    libportaudio2 libx11-6 libxcb1 libxkbcommon0 libpulse0
# copy the sources in, then:
limactl shell wdlinux -- bash -c 'cd ~/whisper-build && python3 -m venv .venv && \
    ./.venv/bin/pip install -r requirements.txt pyinstaller && \
    ./scripts/build_release_linux.sh --tar'
```

The VM is a build host, not an artifact: stop it (`limactl stop wdlinux`) when
you are done so it stops using 8 GB of RAM, and delete it
(`limactl delete wdlinux`) if the base image is stale.

## Publishing

```bash
./scripts/publish_release.sh dist/*.zip dist/*.tar.gz
```

The script uploads to `rorshopping/whisper-dictate-releases` (public), replaces
an asset of the same name instead of making `name-1`, and then verifies the
result is anonymously downloadable — the source repository is private, so a link
into it would 404 for every visitor.

The website (`becker-hub-web`, page `/whisper-dictate`) reads that repository's
latest release through `src/lib/whisperReleases.ts`; it needs no deploy after an
upload, only a page reload once the one-hour cache expires. An unsigned artifact
is labelled as such on the page (`-unsigned` in the filename is what the
classifier looks for).
