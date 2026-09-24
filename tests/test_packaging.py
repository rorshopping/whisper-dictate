"""Static checks for the packaging templates.

These tests intentionally inspect text only: they must run on any development
machine without Inno Setup, macOS, Docker, or network access.
"""

import re
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
PACKAGING = ROOT / "packaging"
WINDOWS_SCRIPT = PACKAGING / "windows" / "WhisperDictate.iss"
MACOS_SCRIPT = PACKAGING / "macos" / "build_signed_dmg.sh"
PACKAGING_README = PACKAGING / "README.md"


def read(path: Path) -> str:
    return path.read_text(encoding="utf-8")


def section(text: str, name: str) -> str:
    """Return one Pascal/Inno section without a full parser dependency."""
    match = re.search(
        rf"(?ms)^\[{re.escape(name)}\]\s*\n(.*?)(?=^\[|\Z)", text
    )
    if match is None:
        raise AssertionError(f"section not found: [{name}]")
    return match.group(1)


class WindowsTemplateTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.text = read(WINDOWS_SCRIPT)
        cls.files = section(cls.text, "Files")

    def test_required_inno_directives_are_present(self):
        required = (
            "AppVersion={#MyAppVersion}",
            "DefaultDirName={localappdata}",
            "PrivilegesRequired=lowest",
            "PrivilegesRequiredOverridesAllowed=",
            "ArchitecturesAllowed=x64",
            "UsePreviousAppDir=no",
            "Uninstallable=yes",
            'Source: "{#MyPayloadDir}\\*"',
            "{cm:CreateStartMenuShortcut}",
            "{cm:CreateDesktopIcon}",
        )
        for directive in required:
            with self.subTest(directive=directive):
                self.assertIn(directive, self.text)

    def test_default_install_is_per_user_and_user_writable(self):
        self.assertNotIn("DefaultDirName={autopf}", self.text)
        self.assertNotIn("DefaultDirName={commonpf}", self.text)
        self.assertIn('Name: "{app}"; Permissions: users-modify', self.text)

    def test_spec_declares_only_existing_text_resources(self):
        for resource in (
            "config.json",
            "hotwords-en.txt",
            "hotwords-de.txt",
            "corrections-en.txt",
            "corrections-de.txt",
            "snippets-en.txt",
            "snippets-de.txt",
            "README.md",
            "LICENSE",
        ):
            with self.subTest(resource=resource):
                self.assertTrue((ROOT / resource).is_file())

    def test_payload_source_has_no_install_time_model_source(self):
        # The Files section may only consume the prepared onedir payload; it
        # must not add a model archive, model cache, or download step.
        for forbidden in (
            "models\\*",
            "model-cache\\*",
            "huggingface\\*",
            "*.safetensors",
            "*.gguf",
            "*.ckpt",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.files)
        self.assertNotRegex(self.files, r"(?im)^\s*Source:.*\bmodels?\b")
        self.assertNotIn("URLDownload", self.text)
        self.assertNotIn("AfterInstall", self.text)


class MacOSDocumentationTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.script = read(MACOS_SCRIPT)
        cls.docs = read(PACKAGING_README)

    def test_macos_template_has_architecture_and_signing_gates(self):
        for marker in (
            "arm64",
            "DEVELOPER_ID_APPLICATION",
            "Developer ID Application:",
            "NOTARYTOOL_PROFILE",
            "codesign --verify",
            "xcrun notarytool submit",
            "xcrun stapler staple",
            "spctl --assess",
        ):
            with self.subTest(marker=marker):
                self.assertIn(marker, self.script)

    def test_macos_template_does_not_embed_credentials_or_identity(self):
        for forbidden in (
            "AuthKey_",
            "issuer_id",
            "--apple-id",
            "--password",
            "PRIVATE KEY",
        ):
            with self.subTest(forbidden=forbidden):
                self.assertNotIn(forbidden, self.script)

    def test_packaging_documentation_links_all_inputs(self):
        links = (
            "[`WhisperDictate.spec`](../WhisperDictate.spec)",
            "[`windows/WhisperDictate.iss`](windows/WhisperDictate.iss)",
            "[`macos/build_signed_dmg.sh`](macos/build_signed_dmg.sh)",
            "[`macos/entitlements.plist`](macos/entitlements.plist)",
            "[`../COMMUNITY_RELEASE_DECISION.md`](../COMMUNITY_RELEASE_DECISION.md)",
        )
        for link in links:
            with self.subTest(link=link):
                self.assertIn(link, self.docs)

        # Resolve the local links without requiring a browser or network.
        for relative in (
            "../WhisperDictate.spec",
            "windows/WhisperDictate.iss",
            "macos/build_signed_dmg.sh",
            "macos/entitlements.plist",
            "../COMMUNITY_RELEASE_DECISION.md",
        ):
            with self.subTest(path=relative):
                self.assertTrue((PACKAGING / relative).resolve().is_file())


if __name__ == "__main__":
    unittest.main()
