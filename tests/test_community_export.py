import hashlib
import json
import sys
import tempfile
import textwrap
import unittest
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from export_community import (
    MANIFEST_NAME,
    ExportError,
    build_artifacts,
    export_community,
    is_denied,
)


class CommunityExportTests(unittest.TestCase):
    def make_fixture(self, root: Path) -> None:
        def write(relative: str, text: str) -> None:
            path = root / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text(textwrap.dedent(text), encoding="utf-8")

        write(
            "main.py",
            """\
            import license_gate
            import tkinter

            DEFAULTS = {
                "license_required": True,
                "license_api": "https://whisperdictate.vercel.app/api",
                "offline": True,
            }

            def main():
                if not DOCTOR and not license_gate.ensure_licensed(cfg, log):
                    log("No license - exiting (start again to activate, or see "
                        "https://whisperdictate.vercel.app)")
                    return
                # Broadcast message fetched during license revalidation (notice.json).
                notice = license_gate.pending_notice()
                if notice:
                    try:
                        icon.notify(notice["message"], APP_NAME)
                    except Exception:
                        pass
            """,
        )
        write(
            "README.md",
            """\
            # Community fixture

            A local desktop app.

            ## License, buying, and releases

            Start a free 14-day trial at https://whisperdictate.vercel.app.
            See [STRIPE.md](STRIPE.md) and the PolyForm Free Trial license.
            """,
        )
        write(
            "COMMUNITY_RELEASE_DECISION.md",
            "# Community Release Decision\n\nThe community source has no account requirement.\n",
        )
        write(
            "THIRD-PARTY-NOTICES.md",
            "# Third-Party Notices\n\nfixture third-party license text\n",
        )
        write(
            "config.json",
            json.dumps(
                {
                    "offline": True,
                    "license_required": True,
                    "license_api": "https://whisperdictate.vercel.app/api",
                    "nested": {"secret_key": "do-not-export", "safe": "kept"},
                    "profiles": [{"name": "EN"}],
                }
            ),
        )
        write("assets/sounds/SOURCES.md", "# CC0 sound sources\n")
        write("assets/sounds/manifest.json", "[]\n")
        write("FEATURE_IDEAS.md", "# Feature ideas\n")

        # None of these should be selected, even though they sit beside the
        # allowlisted source files in a review fixture.
        write("license_gate.py", "paid = True\n")
        write("tests/test_license_gate.py", "paid = True\n")
        write("STRIPE.md", "payment documentation\n")
        write("MARKETING-LAUNCH.md", "launch copy\n")
        write("website/api/activate.js", "paid route\n")
        write("build/output.exe", "built")
        write("dist/package.zip", "built")
        write(".venv/Lib/site-packages/secret.py", "venv")
        write("dictate.log", "local log")
        write("transcription-history.jsonl", '{"text":"private"}\n')
        write(".env", "STRIPE_SECRET_KEY=do-not-copy\n")
        write("secrets.txt", "private key material\n")
        write("personal-notes.md", "personal\n")
        write("model.safetensors", "weights")
        write("not-in-allowlist.py", "must stay out\n")
        write("assets/sounds/not-in-allowlist.wav", "not a bundled cue\n")

    def test_allowlist_generation_and_manifest(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            output = base / "community-output"
            source.mkdir()
            self.make_fixture(source)
            original_main = (source / "main.py").read_bytes()

            result = export_community(source, output)

            self.assertEqual(result, output.resolve())
            self.assertEqual((source / "main.py").read_bytes(), original_main)
            self.assertTrue((output / "LICENSE").is_file())
            self.assertTrue((output / "MODEL_LICENSES.md").is_file())
            self.assertTrue((output / MANIFEST_NAME).is_file())
            for expected in (
                "README.md",
                "COMMUNITY_RELEASE_DECISION.md",
                "THIRD-PARTY-NOTICES.md",
                "main.py",
                "config.json",
                "assets/sounds/SOURCES.md",
            ):
                self.assertTrue((output / expected).is_file(), expected)
            self.assertEqual(
                (output / "THIRD-PARTY-NOTICES.md").read_bytes(),
                (source / "THIRD-PARTY-NOTICES.md").read_bytes(),
            )

            for excluded in (
                "license_gate.py",
                "tests/test_license_gate.py",
                "STRIPE.md",
                "MARKETING-LAUNCH.md",
                "website",
                "build",
                "dist",
                ".venv",
                "dictate.log",
                "transcription-history.jsonl",
                ".env",
                "secrets.txt",
                "personal-notes.md",
                "model.safetensors",
                "not-in-allowlist.py",
            ):
                self.assertFalse((output / excluded).exists(), excluded)

            license_text = (output / "LICENSE").read_text(encoding="utf-8")
            self.assertIn("MIT License", license_text)
            self.assertIn("first-party source", license_text)
            self.assertNotIn("PolyForm", license_text)
            self.assertNotIn("Stripe", license_text)

            model_text = (output / "MODEL_LICENSES.md").read_text(encoding="utf-8")
            self.assertIn("NVIDIA Open Model License", model_text)
            self.assertIn("OpenMDW-1.1", model_text)
            self.assertIn("downloaded separately", model_text)
            self.assertIn("not covered by the first-party", model_text)
            self.assertIn(
                "https://www.nvidia.com/en-us/agreements/enterprise-software/nvidia-open-model-license/",
                model_text,
            )
            self.assertIn("https://openmdw.ai/license/1-1/", model_text)

            main_text = (output / "main.py").read_text(encoding="utf-8")
            self.assertNotIn("license_gate", main_text)
            self.assertNotIn("whisperdictate.vercel.app", main_text)
            self.assertNotIn("license_required", main_text)
            self.assertNotIn("license_api", main_text)
            config = json.loads((output / "config.json").read_text(encoding="utf-8"))
            self.assertTrue(config["offline"])
            self.assertEqual(config["nested"], {"safe": "kept"})
            self.assertNotIn("secret_key", config["nested"])

            manifest = json.loads((output / MANIFEST_NAME).read_text(encoding="utf-8"))
            entries = manifest["files"]
            paths = [entry["path"] for entry in entries]
            self.assertEqual(paths, sorted(paths))
            self.assertNotIn(MANIFEST_NAME, paths)
            for entry in entries:
                path = output / Path(entry["path"])
                self.assertTrue(path.is_file(), entry["path"])
                data = path.read_bytes()
                self.assertEqual(len(data), entry["size"])
                self.assertEqual(hashlib.sha256(data).hexdigest(), entry["sha256"])

    def test_nonempty_output_requires_explicit_force(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            output = base / "community-output"
            source.mkdir()
            self.make_fixture(source)
            output.mkdir()
            (output / "keep.txt").write_text("do not delete", encoding="utf-8")

            with self.assertRaises(ExportError):
                export_community(source, output)
            self.assertEqual((output / "keep.txt").read_text(), "do not delete")

            export_community(source, output, force=True)
            self.assertFalse((output / "keep.txt").exists())
            self.assertTrue((output / MANIFEST_NAME).is_file())

    def test_repeated_exports_are_byte_deterministic(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source.mkdir()
            self.make_fixture(source)
            first = base / "first"
            second = base / "second"
            export_community(source, first)
            export_community(source, second)

            def tree_bytes(root: Path):
                return {
                    path.relative_to(root).as_posix(): path.read_bytes()
                    for path in root.rglob("*")
                    if path.is_file()
                }

            self.assertEqual(tree_bytes(first), tree_bytes(second))

    def test_source_and_output_path_overlap_is_rejected(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            source.mkdir()
            self.make_fixture(source)
            with self.assertRaises(ExportError):
                export_community(source, source)
            with self.assertRaises(ExportError):
                export_community(source, source / "inside")
            self.assertFalse((source / "inside").exists())

    def test_symlink_output_is_refused_when_platform_allows_creating_one(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            target = base / "target"
            link = base / "output-link"
            source.mkdir()
            target.mkdir()
            self.make_fixture(source)
            try:
                link.symlink_to(target, target_is_directory=True)
            except (OSError, NotImplementedError) as exc:
                self.skipTest(f"directory symlinks unavailable: {exc}")
            with self.assertRaises(ExportError):
                export_community(source, link)

    def test_policy_rejects_sensitive_paths(self):
        self.assertTrue(is_denied("website/api/activate.js"))
        self.assertTrue(is_denied("tests/test_license_gate.py"))
        self.assertTrue(is_denied("build/output.exe"))
        self.assertTrue(is_denied("dist/package.zip"))
        self.assertTrue(is_denied(".venv/Lib/site-packages/secret.py"))
        self.assertTrue(is_denied("config.local.json"))
        self.assertFalse(is_denied("README.md"))

    def test_build_artifacts_does_not_touch_a_destination(self):
        with tempfile.TemporaryDirectory() as tmp:
            base = Path(tmp)
            source = base / "source"
            output = base / "never-created"
            source.mkdir()
            self.make_fixture(source)
            artifacts = build_artifacts(source)
            self.assertIn("LICENSE", artifacts)
            self.assertIn(MANIFEST_NAME, artifacts)
            self.assertFalse(output.exists())


if __name__ == "__main__":
    unittest.main()
