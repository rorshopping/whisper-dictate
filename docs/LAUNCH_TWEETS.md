# Launch thread

Rules respected: 280 characters max per tweet, no more than 4 hashtags, and no
tweet depends on an image that is not attached. Numbers below are the ones the
shipped code and the pricing pages actually support — do not inflate them.

Thread order matters: the hook, the problem, the mechanism, the vocabulary
feature, the privacy point, the receipts, the ask.

---

**1/8**

> Dictation tools charge $15/month and send your voice to a server.
>
> I built the opposite: hold a hotkey, speak, release — the text is typed at your cursor. Entirely on your machine.
>
> Free, no account, no word limit. Windows, macOS and Linux.
>
> Whisper Dictate 🧵

**2/8**

> The catch with every cloud dictation app is the same: your microphone is a live feed to someone else's GPU. Legal memos, patient notes, unreleased code — all of it leaves the building.
>
> And then the week's word allowance runs out and it stops.

**3/8**

> Whisper Dictate runs a 0.6B NVIDIA Nemotron streaming model locally.
>
> CPU is fine. It uses your NVIDIA GPU (CUDA) or Apple GPU (MPS) when you have one, and falls back automatically when you don't.
>
> Audio is captured, decoded and typed in one process. Nothing is uploaded, ever.

**4/8**

> The feature I actually use most: it learns *your* words.
>
> Drop your project names, acronyms and people into a text file. After each dictation, near-misses get rewritten to the spelling you wrote down. No retraining, no dashboard, no "custom vocabulary" upsell.

**5/8**

> Two more things generic dictation gets wrong:
>
> → Say "comma" or "new line" and get the real character (opt-in, English + German)
> → Say "my signature" and a block you stored gets typed verbatim
>
> Both are plain text files you own.

**6/8**

> And the one nobody ships: "scratch that".
>
> A hotkey that backspaces exactly the characters of your last dictation. Watch it go wrong at the cursor, erase it, speak again — without touching the mouse.

**7/8**

> Everything is inspectable:
>
> · dictate.log records every step
> · transcription history is a JSONL file you can search
> · the network stays idle after the first model download
> · the source is on GitHub
>
> You can verify the claims instead of trusting them.

**8/8**

> Downloads for Windows, macOS and Linux — free, no account, no word limit:
>
> https://becker-hub-web.vercel.app/whisper-dictate
>
> If you dictate more than 2,000 words a week, this replaces a $15/month subscription.

---

## Single-post variant (if you prefer one tweet)

> Cloud dictation: $15/month, word limits, your voice on someone's server.
>
> Whisper Dictate: hold a hotkey, speak, release — text typed at your cursor, transcription running entirely on your machine. Free and offline on Windows, macOS and Linux.
>
> https://becker-hub-web.vercel.app/whisper-dictate

## Notes on posting

* Attach one real screenshot to tweet 1 (the dictation tape / status pill) or
  none at all — a thread that promises local and shows a stock gradient
  undercuts itself in the first second.
* Send tweet 8 last; the link in the final post keeps reach on the earlier ones.
* Numbers to have ready if anyone asks: first dictation downloads a few hundred
  MB per language profile; the app is 1.1.0; Windows and macOS previews are
  unsigned, so the first launch needs More info → Run anyway / right-click →
  Open.
* If someone reports a platform problem, the honest answer is the Linux one:
  X11 session required for pasting and global hotkeys.
