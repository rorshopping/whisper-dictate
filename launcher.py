"""Launch Whisper Dictate with the optional OpenWhisper-inspired features.

macOS: platform_mac owns everything Darwin-specific (Tk/AppKit startup order,
main-thread paste, Cmd+V injection, stale lock recovery). It must run
prepare() before main is imported and install() after, so keep the calls here -
starting main.py directly on macOS skips them (use run_mac.sh / install.py).

This is also the frozen entry point (packaging/whisper_dictate.spec), so every
start-up flag main.py understands has to be honoured *here*: importing main and
calling main.main() unconditionally would run the app even for --doctor, which
is how the self-check silently became a full launch.
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
    # Same dispatch as main.py's own __main__ block - keep the two in sync.
    if main.DOCTOR:
        main.run_doctor()
    else:
        main.main()
