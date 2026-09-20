"""Startup license gate.

Whisper Dictate requires a license (14-day trial counts) for everyone except
the copyright holder. On startup this module checks the local activation
state (~/.whisperdictate/license.json):

- A signed token from the activation API (whisperdictate.vercel.app/api) is
  validated offline; the signature can only be checked server-side, but the
  token carries the expiry and the state file carries the last successful
  server contact, so the app runs offline for a grace period of 14 days.
- If the state is missing or expired, a Tk dialog collects the purchase
  email (activation), starts the 14-day trial, or opens the buy page.

Everything network-related happens off the UI thread; `ensure_licensed` is
called once from main() on the Tk main thread. Pure helpers (token parsing,
validity windows) live at module level and are unit-tested in
tests/test_license_gate.py.
"""

import base64
import json
import threading
import time
import urllib.request
import uuid
from pathlib import Path

DEFAULT_API = "https://whisperdictate.vercel.app/api"
NOTICE_URL = "https://whisperdictate.vercel.app/notice.json"
LICENSE_DIR = Path.home() / ".whisperdictate"
LICENSE_FILE = LICENSE_DIR / "license.json"
GRACE_DAYS = 14

_buy_url = "https://whisperdictate.vercel.app/#pricing"


def _post(url, payload, timeout=15):
    req = urllib.request.Request(
        url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json"},
    )
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def token_payload(token):
    """Decode (not verify - the server keeps the HMAC secret) a token."""
    try:
        body = token.split(".")[0]
        body += "=" * (-len(body) % 4)
        payload = json.loads(base64.urlsafe_b64decode(body.encode()).decode())
        return payload if isinstance(payload, dict) else {}
    except Exception:
        return {}


def locally_valid(state, now=None):
    """True while the stored token is parseable and inside expiry+grace."""
    now = time.time() if now is None else now
    if not isinstance(state, dict) or not state.get("token"):
        return False
    exp = state.get("exp") or token_payload(state["token"]).get("exp") or 0
    try:
        exp = int(exp)
    except (TypeError, ValueError):
        return False
    last_ok = state.get("last_ok") or 0
    try:
        last_ok = float(last_ok)
    except (TypeError, ValueError):
        last_ok = 0
    if last_ok <= 0:
        last_ok = state.get("activated") or 0
    # Valid until the license expires; past that, an offline grace window
    # measured from the last successful server validation.
    return now < max(exp, last_ok + GRACE_DAYS * 86400)


def load_local(path=LICENSE_FILE):
    try:
        state = json.loads(Path(path).read_text(encoding="utf-8"))
        return state if isinstance(state, dict) else None
    except Exception:
        return None


def save_local(state, path=LICENSE_FILE):
    Path(path).parent.mkdir(parents=True, exist_ok=True)
    Path(path).write_text(
        json.dumps(state, indent=2) + "\n", encoding="utf-8"
    )


def device_id(state):
    device = (state or {}).get("device")
    if not device:
        device = uuid.uuid4().hex
    return device


def _activate(url, endpoint, email, device):
    """Call activate/trial; returns (state, error). Error is None on success."""
    try:
        resp = _post(f"{url}/{endpoint}", {"email": email, "device": device})
    except Exception as exc:
        return None, f"Could not reach the license server: {exc}"
    state = {
        "token": resp["token"],
        "email": resp.get("email", email),
        "device": device,
        "exp": resp.get("exp", 0),
        "activated": time.time(),
        "last_ok": time.time(),
        "trial": bool(resp.get("trial")),
    }
    return state, None


_notice_pending = None  # set by revalidate_async when a new notice arrives


def pending_notice():
    """Broadcast message fetched during revalidation (shown once by main)."""
    global _notice_pending
    notice = _notice_pending
    _notice_pending = None
    return notice


def _check_notice(state):
    """Fetch the public broadcast file; stash it when newer than seen."""
    global _notice_pending
    try:
        req = urllib.request.Request(NOTICE_URL, headers={"Cache-Control": "no-cache"})
        with urllib.request.urlopen(req, timeout=10) as resp:
            notice = json.loads(resp.read().decode("utf-8"))
        message = notice.get("message")
        if message and notice.get("updated") != state.get("notice_seen"):
            _notice_pending = {
                "message": message,
                "url": notice.get("url"),
                "updated": notice.get("updated"),
            }
            state["notice_seen"] = notice.get("updated")
            save_local(state)
    except Exception:
        pass


def revalidate_async(cfg=None, log=None):
    """Refresh last_ok/token in the background; never blocks or raises."""

    def work():
        state = load_local()
        if not state or not state.get("token"):
            return
        url = (cfg or {}).get("license_api", DEFAULT_API)
        try:
            resp = _post(f"{url}/validate", {"token": state["token"]})
            state["token"] = resp.get("token", state["token"])
            state["exp"] = resp.get("exp", state.get("exp", 0))
            state["last_ok"] = time.time()
            save_local(state)
            if log:
                log("License revalidated")
            _check_notice(state)
        except urllib.error.HTTPError as exc:
            if exc.code == 403 and state.get("email"):
                # License expired/revoked server-side: re-run activation, so a
                # renewed subscription extends us without any user action.
                new_state, err = _activate(url, "activate", state["email"], state["device"])
                if new_state:
                    save_local(new_state)
                    if log:
                        log("License renewed via re-activation")
                elif log:
                    log(f"License re-activation failed: {err}")
            elif log:
                log(f"License revalidation failed: HTTP {exc.code}")
        except Exception as exc:
            if log:
                log(f"License revalidation skipped: {exc}")

    threading.Thread(target=work, daemon=True, name="license-revalidate").start()


def ensure_licensed(cfg=None, log=None, force_dialog=False):
    """Gate main(): True when a license/trial is present, else show the
    activation dialog and return whether activation succeeded."""
    cfg = cfg or {}
    if not cfg.get("license_required", True):
        return True
    url = cfg.get("license_api", DEFAULT_API)
    state = load_local()
    if state:
        state["device"] = device_id(state)
    if not force_dialog and locally_valid(state):
        revalidate_async(cfg, log)
        return True
    if state and not locally_valid(state):
        expired = True
    else:
        expired = False

    import tkinter as tk
    import webbrowser

    device = device_id(state)
    root = tk.Tk()
    root.title("Whisper Dictate — Activation")
    root.resizable(False, False)
    root.attributes("-topmost", True)
    frm = tk.Frame(root, padx=18, pady=14)
    frm.pack()
    tk.Label(
        frm,
        text="Whisper Dictate",
        font=("TkDefaultFont", 13, "bold"),
    ).pack(anchor="w")
    msg = (
        "Your trial or license has expired."
        if expired
        else "Whisper Dictate requires a license — start with a free 14-day trial.\n"
        "One email, no card. Fully local: audio never leaves this machine."
    )
    tk.Label(frm, text=msg, justify="left", wraplength=380).pack(
        anchor="w", pady=(6, 10)
    )
    row = tk.Frame(frm)
    row.pack(fill="x")
    tk.Label(row, text="Email:").pack(side="left")
    entry = tk.Entry(row, width=32)
    entry.pack(side="left", padx=6)
    if state and state.get("email"):
        entry.insert(0, state["email"])
    status = tk.Label(frm, text="", fg="#b45309", justify="left", wraplength=380)
    status.pack(anchor="w", pady=(8, 4))

    result = {"ok": False}

    def finish(new_state):
        save_local(new_state)
        result["ok"] = True
        root.destroy()

    def start_trial():
        status.config(text="Starting trial…", fg="#555555")
        new_state, err = _activate(url, "trial", entry.get().strip(), device)
        if err:
            status.config(text=err, fg="#b91c1c")
        else:
            finish(new_state)

    def activate():
        status.config(text="Activating…", fg="#555555")
        new_state, err = _activate(url, "activate", entry.get().strip(), device)
        if err:
            status.config(text=err, fg="#b91c1c")
        else:
            finish(new_state)

    def buy():
        webbrowser.open(_buy_url)

    buttons = tk.Frame(frm)
    buttons.pack(fill="x", pady=(6, 0))
    tk.Button(buttons, text="Start free 14-day trial", command=start_trial).pack(
        side="left"
    )
    tk.Button(buttons, text="Activate license", command=activate).pack(
        side="left", padx=6
    )
    tk.Button(buttons, text="Buy (€40/year)", command=buy).pack(side="right")
    root.protocol("WM_DELETE_WINDOW", root.destroy)

    # Center the dialog.
    root.update_idletasks()
    sw, sh = root.winfo_screenwidth(), root.winfo_screenheight()
    root.geometry(f"+{(sw - root.winfo_width()) // 2}+{(sh - root.winfo_height()) // 2}")
    root.mainloop()

    if result["ok"] and log:
        log(f"Licensed to {load_local().get('email')}")
    return result["ok"]
