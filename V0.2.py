# V0.2.py

import os
import sys
import subprocess

# Import actual modules available in this repository
from hostility_handler import HostilityLevel, handle_message
from unified_transcript import export_to_json


# Hostility detection function
class HostilityDetector:
    def __init__(self):
        pass

    def analyze_text(self, text: str, user_key: str = "local", username: str = "local", platform: str = "cli"):
        # Analyze text for hostility using hostility_handler
        result = handle_message(text, user_key=user_key, username=username, platform=platform)
        return result


# Function to export the current session transcript to a JSON file
def export_transcript(output_path: str = "") -> str:
    return export_to_json(output_path=output_path)


# UI implementation — launches the full bot (quiet_reach V0.2.py)
class UserInterface:
    def __init__(self):
        self._proc = None

    def display(self):
        # Launch the actual bot control panel
        bot_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "quiet_reach V0.2.py")
        if not os.path.isfile(bot_path):
            raise FileNotFoundError(f"Main bot file not found: {bot_path!r}")
        try:
            # Pass path as a list element so spaces in the filename are handled correctly
            self._proc = subprocess.Popen([sys.executable, bot_path])
            self._proc.wait()
        finally:
            if self._proc is not None:
                try:
                    self._proc.terminate()
                except OSError:
                    pass
                self._proc = None


if __name__ == '__main__':
    # Example usage
    detector = HostilityDetector()
    print(detector.analyze_text('Sample text'))
    ui = UserInterface()
    ui.display()
