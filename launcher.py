"""Launch Whisper Dictate with the optional OpenWhisper-inspired features."""

import enhanced_features
import main


enhanced_features.install()

if __name__ == "__main__":
    main.main()
