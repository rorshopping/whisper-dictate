# Linux notes (download page copy)

Whisper Dictate for Linux is a single tarball. Unpack it and run the binary —
there is no installer and nothing to configure first.

```bash
tar -xzf WhisperDictate-1.1.0-linux-x86_64.tar.gz
cd WhisperDictate
./Whisper\ Dictate
```

## Requirements

The bundle contains Python and every dependency, but it uses the host's audio
and window-system libraries, which cannot be bundled:

| Library | Why |
|---|---|
| `libportaudio2` | microphone capture |
| `libx11-6`, `libxcb1` | X11 session and synthetic paste |
| `libxkbcommon0` | keyboard layout |
| `libasound2` or `libpulse0` | audio backend |

On Debian/Ubuntu:

```bash
sudo apt install libportaudio2 libx11-6 libxcb1 libxkbcommon0 libpulse0
```

On Fedora:

```bash
sudo dnf install portaudio libX11 libxcb libxkbcommon pulseaudio-libs
```

`--doctor` prints exactly what is missing if the app refuses to start:

```bash
./Whisper\ Dictate --doctor
```

## Session type: X11

**Use an X11 session.** Recording works under PipeWire and PulseAudio, but the
paste and the global hotkeys use the X11 input API. On a Wayland session the
paste only works while XWayland is present, and global hotkeys may not be
captured at all. On GNOME, pick "GNOME on Xorg" at the login screen; on KDE,
choose an X11 session.

## Permissions

No special permissions are needed. The app listens for its hotkeys, records the
microphone while a hotkey is held, and pastes the transcription at the cursor.

## Does it phone home?

No. Audio never leaves the machine. The only network access is the one-time
model download from Hugging Face on first use — after that the app runs with
`HF_HUB_OFFLINE=1` and makes no requests at all.
