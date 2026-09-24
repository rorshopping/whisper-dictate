# Resolver-to-profile wiring notes

## What is wired

`main.py` now keeps the original profile mapping on each `Profile` and applies
`model_manager.parse_model_config()` lazily when a Nemotron model is loaded.
This preserves the existing `name`, `model`, `engine`, `language`, hotword,
correction, label, and hotkey fields while giving the resolver the complete
configuration precedence rules:

1. profile-level resolver keys;
2. the top-level `model_resolver` block; and
3. the application's normal top-level `offline` default.

`get_model()` passes the resulting settings to `NemotronModel` as optional
keyword arguments: `revision`, `source_order`, `mirror_url`,
`huggingface_endpoint`, `offline`, `cache_dir`, `local_model_path`,
`local_model_dir`, `cache_path`, and an optional custom manifest.  The profile
language is also passed explicitly so resolver validation and the multilingual
processor prompt use the same language.  The model identity is selected from
`model_id` when a custom local snapshot supplies one; the existing profile
`model` value remains the normal/default identity.

The faster-whisper branch is deliberately unchanged.  It still constructs
`WhisperModel(profile.model, device=..., compute_type=...)` and does not receive
Nemotron-only resolver arguments.  The direct positional
`NemotronModel(model_id, device, compute_type, log)` API also remains valid;
new resolver arguments are keyword-only and an embedding/test harness can
inject a compatible resolver.

## Cache and source behavior

`MODEL_CACHE_DIR` is computed once by `app_paths.model_cache_dir()` and is
passed explicitly as `cache_dir`.  The resolver therefore uses the selected
application path in both modes rather than consulting `HF_HUB_CACHE`,
`HF_HOME`, or its own home-directory default.  The bundled legacy home-cache
value is treated as a default and replaced by the selected app path; an
operator's explicit non-default cache remains configurable.  A source checkout
keeps the historical Hugging Face cache; frozen and portable installations keep
the writable `models/` directory selected by `app_paths`.  An explicit profile
local snapshot remains strict and is passed as `local_model_path`.

The resolver's source order and mirror/Hugging Face endpoint remain independent
of the cache location.  A configured HTTPS mirror can precede the pinned
Hugging Face endpoint, but neither is a hidden fallback around a failed local
model load.

## Error behavior

Resolver construction happens inside the existing `get_model()` `try` block.
Missing, incomplete, and integrity-check failures are logged with the profile
name and re-raised to the existing preload/transcription error path.  The code
does not catch those errors and retry through Transformers or another cloud
source, so a corrupt pinned snapshot cannot be silently replaced by an
unverified checkpoint.

No `app_paths.py` change was needed for this wiring: the important correction
is passing its already-selected `MODEL_CACHE_DIR` explicitly.  Keeping the
existing Windows/macOS/Linux data-root policy avoids an unrelated migration of
user configuration and history.  A future path-policy change (for example,
choosing a local rather than roaming Windows directory) should be made with a
separate migration and regression test.

## Tests

`tests/test_profile_model_wiring.py` loads the application bridge with mocked
optional desktop/audio dependencies and verifies that profile resolver settings
and the app-selected cache reach a fake `NemotronModel`.  It also checks that
resolver errors remain visible and that faster-whisper construction is
unchanged.  `tests/test_nemotron_model_resolution.py` covers the legacy
positional/direct-ID constructor shape alongside the existing local-snapshot
and integrity tests.

## Remaining product work

* Add a settings UI for per-profile revisions, source order, mirror/endpoint,
  offline policy, and explicit local snapshots.  The JSON schema is ready, but
  the current tray UI does not edit resolver fields.
* Connect the resolver's `download_hook` to a cancellable/status-pill or tray
  progress view.  The manager already emits download events, but the normal
  model-load path currently reports only loading/failure states.
* Extend the doctor/preflight screen to use `ModelManager.validate()` and show
  missing-file, size, and SHA-256 details before torch is imported.  A repair
  or quarantine action should be explicit and must not turn into an implicit
  cloud fallback.
* Decide how first-use downloads should be presented when offline mode is
  enabled but no complete local snapshot exists, and whether a user-facing
  opt-in should relax the strict offline setting.
