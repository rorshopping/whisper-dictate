"""Opt-in, real macOS release acceptance test (not a mocked unit test).

Run: .venv/bin/python tests/integration/test_macos_release.py
Requires Developer ID + the configured notarytool keychain profile. The build
is skipped when credentials are unavailable, but the existing artifact is still
assessed so a developer signature cannot be mistaken for a release signature.
This never publishes anything. A credential failure is a FAILED test, not a skip.
"""
import os
from pathlib import Path
import subprocess
import sys
import unittest

ROOT = Path(__file__).resolve().parents[2]
APP = ROOT / "dist" / "Whisper Dictate.app"


class MacOSReleaseIntegration(unittest.TestCase):
    def test_build_sign_and_gatekeeper_acceptance(self):
        self.assertEqual(sys.platform, "darwin", "Must run on the actual macOS build host")
        failures = []

        def run(label, command, timeout=120):
            print(f"\n== {label} ==", flush=True)
            try:
                result = subprocess.run(command, cwd=ROOT, text=True,
                                        stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                                        timeout=timeout)
            except subprocess.TimeoutExpired:
                failures.append(f"{label}: timed out after {timeout}s")
                return False
            print(result.stdout, flush=True)
            if result.returncode:
                failures.append(f"{label}: exit {result.returncode}")
                return False
            return result.stdout or True

        identities = run("Signing identities", ["security", "find-identity", "-v", "-p", "codesigning"])
        can_build = isinstance(identities, str) and '"Developer ID Application:' in identities
        if not can_build:
            failures.append("Build/sign blocked: no Developer ID Application identity with private key")
        else:
            profile = os.environ.get("NOTARY_PROFILE", "whisper-dictate")
            can_build = bool(run("Notarization credentials", ["xcrun", "notarytool", "history",
                                 "--keychain-profile", profile, "--output-format", "json"]))
        if can_build:
            run("Build, sign and notarize", ["bash", "scripts/build_release.sh",
                                             "--sign", "--notarize", "--zip"], timeout=3600)
        else:
            print("No build attempted; assessing the existing artifact without modifying it.", flush=True)

        if not APP.is_dir():
            failures.append(f"Missing app artifact: {APP}")
        else:
            run("Actual artifact signature integrity", ["codesign", "--verify", "--deep",
                                                        "--strict", "--verbose=2", str(APP)])
            details = run("Actual artifact signer", ["codesign", "--display", "--verbose=4", str(APP)])
            if not isinstance(details, str) or "Authority=Developer ID Application:" not in details:
                failures.append("Actual artifact lacks a Developer ID Application signature")
            if not isinstance(details, str) or "TeamIdentifier=AGYVQ59A5S" not in details:
                failures.append("Actual artifact does not identify the expected signing team")
            run("Actual artifact Gatekeeper acceptance", ["spctl", "--assess", "--type", "execute",
                                                          "--verbose=4", str(APP)])
            run("Actual artifact notarization ticket", ["xcrun", "stapler", "validate", str(APP)])
        self.assertFalse(failures, "Release acceptance FAILED:\n- " + "\n- ".join(failures))


if __name__ == "__main__":
    unittest.main(verbosity=2)
