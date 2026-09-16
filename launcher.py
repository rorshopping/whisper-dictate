"""Launch Whisper Dictate with the optional OpenWhisper-inspired features.

macOS: platform_mac owns everything Darwin-specific (Tk/AppKit startup order,
main-thread paste, Cmd+V injection, stale lock recovery). It must run
prepare() before main is imported and install() after, so keep the calls here -
starting main.py directly on macOS skips them (use run_mac.sh / install.py).
"""

import sys

if sys.platform == "darwin":
    import platform_mac

    platform_mac.prepare()

import enhanced_features
import main

if sys.platform == "darwin":
    platform_mac.install()

enhanced_features.install()

if __name__ == "__main__":
    main.main()
