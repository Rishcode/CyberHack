import os
import platform

def get_chrome_profile_path():
    home = os.path.expanduser("~")
    system = platform.system()
    if system == "Windows":
        return os.path.join(home, "AppData", "Local", "Google", "Chrome", "User Data")
    elif system == "Darwin":  # macOS
        return os.path.join(home, "Library", "Application Support", "Google", "Chrome")
    else:  # Linux
        return os.path.join(home, ".config", "google-chrome")

print("Your Chrome profile path is:", get_chrome_profile_path())
