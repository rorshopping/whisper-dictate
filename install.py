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

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
VENV_DIR = os.path.join(BASE_DIR, ".venv")
REQUIREMENTS = os.path.join(BASE_DIR, "requirements.txt")
CUDA_TORCH_INDEX = "https://download.pytorch.org/whl/cu126"


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
