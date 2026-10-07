#!/usr/bin/env python3
"""Whisper Dictate installer - one entry point with an explicit platform switch.

    python install.py                     # auto-detect this machine
    python install.py --platform macos    # macOS setup
    python install.py --platform windows  # Windows setup

What differs between the platforms (everything else is shared):

* Dependencies - the CUDA math libraries are Windows-only and are skipped by
  the environment markers in requirements.txt; macOS needs no extra packages
  (torch ships Apple Silicon wheels). Use --cuda on Windows to also replace
  PyPI's CPU-only torch wheel with the CUDA build.
* Device - ``"device": "auto"`` resolves to CUDA on Windows and to the Apple
  GPU (MPS) on macOS, falling back to the CPU (platform_mac.py).
* Runtime quirks - macOS support lives in platform_mac.py, wired up by
  launcher.py; Windows needs nothing extra (main.py is Windows-first).

The script is safe to re-run: it only creates the virtualenv when missing and
pip install is idempotent. Run it with a system Python, not with the venv.
"""

import argparse
import os
import shutil
import subprocess
import sys
import urllib.request
import zipfile

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(BASE_DIR, ".venv")
REQUIREMENTS = os.path.join(BASE_DIR, "requirements.txt")
CUDA_TORCH_INDEX = "https://download.pytorch.org/whl/cu126"
# parakeet.cpp runtime for the "parakeet-gguf" engine profiles (parakeet_engine.py).
# The CPU build is a ~2 MB self-contained download; for GPU transcription drop the
# CUDA parakeet.dll (+ cublas64_12/cublasLt64_12/cudart64_12 from the cudart zip)
# into the same folder instead - see packaging/README.md.
PARAKEET_VERSION = "v0.5.0"
PARAKEET_LIB_ZIP = (
    "https://github.com/mudler/parakeet.cpp/releases/download/"
    f"{PARAKEET_VERSION}/parakeet-{PARAKEET_VERSION}-lib-win-cpu-x64.zip"
)
PARAKEET_BIN_DIR = os.path.join(BASE_DIR, "packaging", "parakeet-bin")


def detect_platform():
    if sys.platform == "darwin":
        return "macos"
    if os.name == "nt" or sys.platform.startswith("win"):
        return "windows"
    return sys.platform


def venv_python():
    if os.name == "nt":
        return os.path.join(VENV_DIR, "Scripts", "python.exe")
    return os.path.join(VENV_DIR, "bin", "python")


def base_python(platform):
    """The first system interpreter that can build the virtualenv."""
    candidates = (
        ["py -3.12", "py -3", "python"]
        if platform == "windows"
        else ["python3", "python"]
    )
    for candidate in candidates:
        parts = candidate.split()
        if shutil.which(parts[0]):
            return parts
    return None


def run(cmd, check=True, **kwargs):
    print(f"$ {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, check=check, **kwargs)


def ensure_parakeet_runtime():
    """Install the parakeet.cpp runtime DLL for the gguf engine profiles.

    Skipped when a runtime is already staged (a previously fetched CPU build
    or a hand-staged CUDA build). Never overwrites an existing parakeet.dll.
    """
    dll = os.path.join(PARAKEET_BIN_DIR, "parakeet.dll")
    if os.path.exists(dll):
        print(f"parakeet runtime already staged: {dll}")
        return
    print(f"Downloading the parakeet.cpp {PARAKEET_VERSION} runtime (~2 MB)")
    os.makedirs(PARAKEET_BIN_DIR, exist_ok=True)
    zip_path = os.path.join(PARAKEET_BIN_DIR, "parakeet-lib.zip")
    try:
        with urllib.request.urlopen(PARAKEET_LIB_ZIP, timeout=120) as response:
            with open(zip_path, "wb") as handle:
                shutil.copyfileobj(response, handle)
        with zipfile.ZipFile(zip_path) as archive:
            names = [n for n in archive.namelist() if n.endswith("parakeet.dll")]
            if len(names) != 1:
                raise RuntimeError(f"unexpected archive layout: {archive.namelist()}")
            with archive.open(names[0]) as source, open(dll, "wb") as target:
                shutil.copyfileobj(source, target)
    except Exception as exc:
        print(
            f"Could not fetch the parakeet runtime ({exc}). The gguf engine "
            "profiles will not load; torch-based profiles are unaffected.",
            file=sys.stderr,
        )
        return
    finally:
        if os.path.exists(zip_path):
            os.remove(zip_path)
    print(f"parakeet runtime staged: {dll}")


def main():
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument(
        "--platform",
        choices=["auto", "macos", "windows"],
        default="auto",
        help="which platform to set up (default: auto-detect this machine)",
    )
    parser.add_argument(
        "--cuda",
        action="store_true",
        help="Windows only: install the CUDA build of torch (nvidia GPUs)",
    )
    parser.add_argument(
        "--no-parakeet",
        action="store_true",
        help="Windows only: skip fetching the parakeet.cpp runtime DLL",
    )
    parser.add_argument(
        "--no-doctor",
        action="store_true",
        help="skip the --doctor self-check at the end",
    )
    args = parser.parse_args()

    platform = detect_platform() if args.platform == "auto" else args.platform
    current = detect_platform()
    if platform != current:
        print(
            f"This machine is {current}, so it cannot install the {platform} "
            f"setup. Run install.py on that machine instead.",
            file=sys.stderr,
        )
        return 2

    if platform not in ("macos", "windows"):
        print(f"Unsupported platform: {platform}", file=sys.stderr)
        return 2

    if args.cuda and platform != "windows":
        print("--cuda only applies to the Windows setup", file=sys.stderr)
        return 2

    python = venv_python()
    if not os.path.exists(python):
        base = base_python(platform)
        if base is None:
            print(
                "No usable Python found. On Windows install Python 3.12 "
                "(py launcher) and re-run; on macOS install it with "
                "'brew install python'.",
                file=sys.stderr,
            )
            return 1
        print(f"Creating the virtualenv ({platform}) in {VENV_DIR}")
        run(base + ["-m", "venv", VENV_DIR])
    else:
        print(f"Using the existing virtualenv in {VENV_DIR}")

    run([python, "-m", "pip", "install", "--upgrade", "pip"])
    if args.cuda:
        print("Installing the CUDA build of torch (this is a large download)")
        run(
            [
                python,
                "-m",
                "pip",
                "install",
                "torch",
                "--index-url",
                CUDA_TORCH_INDEX,
            ]
        )
    run([python, "-m", "pip", "install", "-r", REQUIREMENTS])

    if platform == "windows" and not args.no_parakeet:
        ensure_parakeet_runtime()

    if not args.no_doctor:
        print()
        run([python, os.path.join(BASE_DIR, "main.py"), "--doctor"], check=False)

    print()
    if platform == "windows":
        print("Installed for Windows. Start with run.bat (or run_hidden.vbs),")
        print("or use the Start Menu / Startup shortcut setup you already have.")
        print(
            "For GPU transcription, re-run with --cuda (or install the CUDA "
            "torch build into .venv yourself)."
        )
        print(
            "The parakeet.cpp runtime staged above is the CPU build; for GPU "
            "gguf transcription place the CUDA parakeet.dll (+ cudart DLLs) "
            "into packaging/parakeet-bin/ - see packaging/README.md."
        )
        print('Set "device": "auto" and "compute_type": "auto" in config.json.')
    else:
        print("Installed for macOS. Start with:")
        print("    ./run_mac.sh")
        print("macOS support (Tk start-up order, main-thread paste, Cmd+V via")
        print("System Events, Apple GPU default) is provided by platform_mac.py;")
        print("always start through run_mac.sh / launcher.py, not main.py.")
        print("Grant Microphone, Accessibility / Input Monitoring and (on the")
        print("first paste) Automation -> System Events in System Settings ->")
        print("Privacy & Security -- see README 'Setup (macOS)'.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
