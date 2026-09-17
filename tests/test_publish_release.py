"""Offline publisher regression checks; gh and curl never reach the network."""

import json
import os
from pathlib import Path
import subprocess
import tempfile
import unittest


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "publish_release.sh"
MOCK_TOOL = r'''#!/usr/bin/env python3
import json
import os
from pathlib import Path
import sys

args = sys.argv[1:]
tool = Path(sys.argv[0]).name
mode = os.environ["TEST_MODE"]
with open(os.environ["TEST_CALLS"], "a") as stream:
    stream.write(json.dumps([tool, args]) + "\n")
if tool == "curl":
    if mode == "http500":
        # Match curl's real HTTP-error behavior: only --fail returns error 22.
        print("500", end="")
        sys.exit(22 if "--fail" in args else 0)
    print("201", end="")
    sys.exit(0)
if args[:2] == ["auth", "token"]:
    print("mock-token")
elif args[0] == "api":
    if mode == "api_failure":
        sys.exit(1)
    endpoint = next(arg for arg in args if arg.startswith("repos/"))
    release = {"id": 7, "tag_name": "v1.1.0", "draft": mode != "public"}
    if "--jq" in args:
        print("7")
    elif endpoint.endswith("/releases"):
        print(json.dumps([[]] if mode == "create" else [[release]]))
    elif endpoint.endswith("/assets"):
        assets = [{"name": "preview with spaces.zip"}] if mode == "collision" else []
        print(json.dumps([assets]))
    else:
        if mode == "became_public":
            release["draft"] = False
        print(json.dumps(release))
'''


class PublishReleaseTests(unittest.TestCase):
    def run_publisher(self, mode):
        with tempfile.TemporaryDirectory(prefix="publisher-test-") as directory:
            root = Path(directory)
            for name in ("gh", "curl"):
                tool = root / name
                tool.write_text(MOCK_TOOL)
                tool.chmod(0o755)
            artifact = root / "preview with spaces.zip"
            artifact.write_bytes(b"mock artifact")
            Path(str(artifact) + ".sha256").write_text("mock checksum")
            calls = root / "calls.jsonl"
            env = dict(
                os.environ,
                PATH=str(root) + os.pathsep + os.environ["PATH"],
                TMPDIR=directory,
                TAG="v1.1.0",
                TEST_MODE=mode,
                TEST_CALLS=str(calls),
            )
            result = subprocess.run(
                ["bash", str(SCRIPT), str(artifact)],
                env=env,
                capture_output=True,
                text=True,
                timeout=30,
            )
            log = [json.loads(line) for line in calls.read_text().splitlines()]
            self.assertFalse(any("DELETE" in args for _, args in log))
            return result, log, str(artifact)

    def test_http500_fails(self):
        result, log, _ = self.run_publisher("http500")
        self.assertEqual(result.returncode, 22, result.stderr)
        self.assertEqual(sum(tool == "curl" for tool, _ in log), 1)
        self.assertNotIn("Nothing was published", result.stdout)

    def test_spaced_paths_preserved(self):
        result, log, artifact = self.run_publisher("spaces")
        self.assertEqual(result.returncode, 0, result.stderr)
        uploads = [args for tool, args in log if tool == "curl"]
        self.assertEqual(len(uploads), 2)
        self.assertEqual(
            [args[args.index("--data-binary") + 1] for args in uploads],
            ["@" + artifact, "@" + artifact + ".sha256"],
        )
        url = next(arg for arg in uploads[0] if arg.startswith("https://uploads.github.com/"))
        self.assertIn("name=preview%20with%20spaces.zip", url)

    def test_public_release_collision_and_api_failure_refused(self):
        for mode in ("public", "became_public", "collision", "api_failure"):
            with self.subTest(mode=mode):
                result, log, _ = self.run_publisher(mode)
                self.assertNotEqual(result.returncode, 0)
                self.assertFalse(any(tool == "curl" for tool, _ in log))
                self.assertFalse(any(args[:2] == ["release", "create"] for _, args in log))

    def test_new_release_is_draft_prerelease(self):
        result, log, _ = self.run_publisher("create")
        self.assertEqual(result.returncode, 0, result.stderr)
        creates = [args for tool, args in log if tool == "gh" and args[:2] == ["release", "create"]]
        self.assertEqual(len(creates), 1)
        self.assertIn("--draft", creates[0])
        self.assertIn("--prerelease", creates[0])


if __name__ == "__main__":
    unittest.main()
