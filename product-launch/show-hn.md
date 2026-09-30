# Show HN draft — Whisper Dictate

Status: DRAFT — do not post yet. Orchestrator reviews first.
Planned where: news.ycombinator.com (Show HN). Links go in the submission URL
field + first comment. Best posted Tue–Thu morning ET.

---

## Title

Show HN: Whisper Dictate – Offline push-to-talk dictation for Windows and macOS

(Submission URL field: https://whisperdictate.vercel.app)

## First comment (Richard's voice)

Hi HN! I'm Richard. I built Whisper Dictate because I got tired of
cloud-dictation tools sending every sentence I say — including code, client
names, and half my private life — to someone else's server.

It's a desktop push-to-talk dictation app: hold a hotkey, speak, release, and
the transcription is pasted at your cursor. Everything runs on your own
machine. Audio never leaves it — there is no server to send it to.

What it does:

- English and German, two switchable profiles with separate hotkeys
- On-device models: NVIDIA Nemotron streaming speech models (0.6B) run on
  your GPU (CUDA on Windows, MPS on Apple silicon), with automatic CPU
  fallback. Faster-whisper profiles are also available if you prefer.
- Built for developers: it handles code terms and API names reasonably well,
  and per-language hotword lists let you teach it your stack's vocabulary.
- Wispr Flow–style auto-edits, fully deterministic and offline: filler words
  are removed, "comma", "new line", "bullet point" become real formatting,
  and "scratch that" drops everything you just said.
- Paste-last-transcription for when you dictated before clicking into the
  right field.

Honest limitations: it wants a GPU. CPU fallback works but streaming latency
is noticeably worse. Two languages only (English, German). Windows and macOS
only — no Linux build yet, mostly because Wayland's screen-level APIs make
global hotkeys and synthetic paste a genuine project of its own.

The main app is source-available: the repo is public
(https://github.com/rorshopping/whisper-dictate — you can read all the code,
issues, docs, release builds, checksums) under a PolyForm Free Trial license.
There's also a free community edition with the smaller
model set at https://github.com/rorshopping/whisper-dictate-community. The
full version is €40/year after a 14-day trial (no card needed for the
trial) — license activation is a signed offline check; the app keeps working
on the free tier if you don't renew.

I use it daily for coding, emails, and writing. Happy to answer questions
about the streaming models, the push-to-talk plumbing on both OSes, or why
German ASR needs an explicit language prompt.

---

## Notes for posting

- Submit as a link post to https://whisperdictate.vercel.app with the title
  above, then immediately post the first comment from the same account.
- Don't editorialize the title ("I made" / "I built" belongs in the comment).
- Reply to early comments within the first hour or two.
