# Pinned model resolver notes

`model_manager.py` is the source boundary for the Nemotron checkpoints.  It
keeps the profile's model identity separate from where the bytes came from, so
an offline installation, an internal mirror, and a first-use Hugging Face
download can use the same loader.

## Manifest format (schema 1)

A manifest is JSON.  A file containing one model can be passed directly to
`load_manifest()`; a catalog uses a top-level `models` array.

```json
{
  "schema_version": 1,
  "id": "nvidia/nemotron-speech-streaming-en-0.6b",
  "revision": "ebe59e5a817142986528bbbee5dba8db7b38ed50",
  "language": "en",
  "model_type": "nemotron_asr_streaming",
  "architectures": ["NemotronAsrStreamingForRNNT"],
  "license": "NVIDIA Open Model License",
  "required_files": [
    {
      "name": "config.json",
      "size": 1284,
      "sha256": "dffe850bc79ad2b0f8117804502b24d2c4a445aafbed4c1e40f8d78e0cb44065"
    },
    {
      "name": "model.safetensors",
      "size": 2472413604,
      "sha256": "bddd8a7300826efd19cf7e01f1c7db8402bed6786fc4c7739632894f69c71473"
    }
  ],
  "optional_files": []
}
```

`revision` is a content revision, not a floating branch such as `main`.
`required_files` is the complete set requested by the current Transformers
path.  The production defaults also include `generation_config.json`,
`processor_config.json`, `tokenizer.json`, and `tokenizer_config.json`.  A
resolver refuses a path escape, a missing size, or a missing/invalid SHA-256.
The manifest dataclasses are frozen, so a loaded identity cannot be edited
while a model is being resolved.

The two documented defaults are embedded in `DEFAULT_MANIFEST_DATA` and can be
obtained as defensive JSON with `default_manifest_data()`:

| Profile | Model | Audited revision | Required bytes | License |
|---|---|---|---:|---|
| EN | `nvidia/nemotron-speech-streaming-en-0.6b` | `ebe59e5a817142986528bbbee5dba8db7b38ed50` | 2,472,816,091 | NVIDIA Open Model License |
| DE / multilingual | `nvidia/nemotron-3.5-asr-streaming-0.6b` | `ea30d66debe3740a08b573244286791d423d6b3e` | 2,552,819,964 | OpenMDW-1.1 |

The small JSON/tokenizer hashes and the model safetensors hashes were audited
against those exact Hugging Face commits on 2026-09-24.  Updating a checkpoint
means adding a new manifest and reviewing its files; it must not mean changing
a branch name in a profile.

## Trust model

There are two separate trust decisions:

1. **Identity and integrity:** the application trusts the checked-in manifest
   as the policy for model ID, revision, language capability, filenames,
   sizes, and SHA-256 values.  Every local or downloaded required file is
   checked before it can be returned.  A hash detects truncation, accidental
   replacement, and a mirror serving different bytes; it does not prove that
   the publisher account or the manifest author is honest.
2. **Source policy:** a configured HTTPS mirror is explicitly trusted by the
   operator to serve those exact bytes.  The resolver still applies the same
   hash checks, and HTTP mirrors are rejected.  A local directory is also
   checked against the manifest; a random directory is not accepted merely
   because it has a `config.json`.

A custom or locally modified model therefore needs its own explicit manifest
and a deliberate profile/configuration change.  Language is part of the
identity: an English-only manifest rejects a non-English profile language, and
the multilingual manifest checks the requested locale before returning a
snapshot.  The resolver never falls back to another model, revision, or
language to make an error disappear.

Only `model.safetensors` and the small Transformers metadata/tokenizer files
are required.  The engine passes `trust_remote_code=False` as well.  NeMo
`.nemo` checkpoints and NeMo-Speech.cpp `.gguf` files are
listed as optional audit metadata where applicable, but are not downloaded or
passed to the current Transformers loader.  That keeps a normal installation
from pulling multiple copies of a multi-gigabyte model.

## Source order and configuration

The default order is:

```text
local -> cache -> mirror -> huggingface
```

`ModelManager` exposes the selected source and every attempt in
`ResolvedModel.trace`; the same trace is available as `manager.last_trace`.
This makes a cache hit, a mirror fallback, and an offline failure visible in
logs rather than silently changing behavior.

The resolver is configured with Python keyword arguments, for example:

```python
manager = ModelManager(
    cache_dir="D:/model-cache/huggingface/hub",
    mirror_url="https://models.example.invalid/nvidia",
    source_order=["local", "cache", "mirror", "huggingface"],
    offline=False,
)
resolved = manager.resolve(
    "nvidia/nemotron-speech-streaming-en-0.6b",
    language="en",
)
```

`parse_model_config()` and `ModelManager.from_config()` read the equivalent
JSON-shaped settings.  The top-level `model_resolver` block and profile-level
keys are intentionally independent of the application's path handling:

```json
{
  "offline": true,
  "model_resolver": {
    "source_order": ["local", "cache", "mirror", "huggingface"],
    "cache_dir": "~/.cache/huggingface/hub",
    "mirror_url": null
  },
  "profiles": [
    {
      "model": "nvidia/nemotron-speech-streaming-en-0.6b",
      "model_revision": "ebe59e5a817142986528bbbee5dba8db7b38ed50",
      "language": "en"
    }
  ]
}
```

An explicit local snapshot can be put in the existing profile `model` field
(as an absolute/`./` path), or supplied as `model_path`/
`local_model_path` to the resolver.  A `model_id` can accompany that path when
using a custom manifest.  An explicit local path is strict: if it is absent,
partial, or corrupt, the error explains what failed instead of quietly moving
to a different source.  In offline mode, only local and complete cache
snapshots are considered.  The Transformers engine always receives the
resulting directory with `local_files_only=True`, so loading a local/offline
model cannot fall through to a network request.

A cache can be either the normal Hugging Face cache root or a direct complete
snapshot (`cache_path`).  A mirror URL can be a base URL (the resolver appends
`model_id/revision/filename`) or a template containing `{model_id}`,
`{revision}`, and `{filename}`.  Only HTTPS is accepted.  The Hugging Face
endpoint is pinned by the manifest revision and can be redirected for an
internal compatible endpoint with `huggingface_endpoint`.

## Download and test seams

The default downloader uses `urllib` and the standard library.  A caller can
inject a `(url, destination)` callable or an object with
`download(url, destination)`.  `sleep` and `download_hook` are injectable too.
Each file is downloaded to a temporary sibling, checked, and published only
after the whole required set validates; a complete staging directory is then
atomically moved into the revision cache.  Interrupted/corrupt old snapshots
are quarantined at commit time.  The `atomic_replace` and `download_hook`
parameters are injectable for platform-specific storage or UI progress
adapters (`download_hook(event, url, destination, attempt, error=None)`).
Retry attempts use bounded exponential backoff (`max_retries`,
`backoff_factor`, and `max_backoff`).

Tests use byte-sized temporary fixtures and fake downloaders.  They never need
to download either multi-gigabyte checkpoint.  `validate_snapshot()` returns a
structured report when `raise_on_error=False`, which is useful for a doctor
command or an installer UI.

## Licensing and distribution caveats

Model weights are not bundled with Whisper Dictate.  The model licenses are
separate from the application and Python dependency licenses:

- The English checkpoint is under the NVIDIA Open Model License.  The required
  attribution is: “Licensed by NVIDIA Corporation under the NVIDIA Open Model
  License.”
- The 3.5 checkpoint is under OpenMDW-1.1; its terms apply to users of the
  weights and outputs.

A mirror operator must be authorized to redistribute the selected files.  A
future package that bundles weights must include the applicable full license
texts and notices, and must review any additional restrictions rather than
assuming the manifest's metadata is a redistribution grant.  See
`THIRD-PARTY-NOTICES.md` for the current model notices.

## Future integration points (not enabled here)

The resolver intentionally has no NIM, cloud API, or other silent fallback.
Future integrations can add a new **source**, rather than bypassing the
manifest:

- A NIM adapter can verify a container/model artifact against a new manifest
  and return the same `ResolvedModel`-style local handle.  It should not be
  selected merely because a local cache is missing.
- NeMo-Speech.cpp/GGUF support can use the optional-file manifest area and a
  separate runtime capability.  The current Transformers resolver must keep
  requesting only its required safetensors/metadata files.
- A future installer or doctor UI can call `ModelManager.validate()` and
  render the structured missing/size/hash report without loading torch.
- A future UI can show `ResolvedModel.source` and `trace` to explain why a
  particular mirror or cache was selected.

Those adapters should preserve the same identity, language, HTTPS, and
integrity checks rather than introducing a second unpinned model path.
