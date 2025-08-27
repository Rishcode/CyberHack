# Instagram Reels Scraper (`insta_final.py`)

Lightweight Selenium automation to log into Instagram, open the Reels feed, and capture screenshots of unique reels.

## 1. Prerequisites

- Google Chrome installed (same major version as matching ChromeDriver bundled with your Selenium install; recent Selenium auto-downloads driver).
- Python 3.10+ recommended.
- Internet connection.
- Instagram account credentials (username & password). If 2FA or challenges appear you may have to finish manually.

## 2. Install Python Dependencies

Create / activate a virtual env (recommended):

```powershell
python -m venv venv
./venv/Scripts/Activate.ps1
```

Install Selenium:

```powershell
pip install --upgrade pip
pip install selenium
```

(If you later need image tooling or hashing libs they can be added, but current script only needs Selenium + stdlib.)

## 3. Environment Variables

Set these in PowerShell (adjust values):

```powershell
$env:INSTA_USERNAME = "your_username"
$env:INSTA_PASSWORD = "your_password"
# Optional overrides:
$env:REEL_TARGET = "80"              # Number of reels to capture (default 50)
$env:CAPTURE = "1"                    # Set to 0 / false to only open Reels and not capture
$env:CHROME_AUTOMATION_DIR = "C:\Temp\insta_automation_profile"  # Custom isolated Chrome profile dir
$env:CHROME_PROFILE_DIR = "Default"   # Typically leave as Default
```

To persist them across sessions you can put `setx` commands (note: setx requires a new shell to take effect):

```powershell
setx INSTA_USERNAME "your_username"
setx INSTA_PASSWORD "your_password"
```

## 4. Run the Script

From the project directory:

```powershell
python .\insta_final.py
```

Process overview:
1. Launches Chrome with an isolated user data dir (prevents locking your real profile).
2. Opens `https://www.instagram.com/reels/`.
3. If not logged in it navigates to login, attempts automatic credential entry.
4. Waits for session cookie; if a challenge/2FA appears you complete it manually.
5. Starts scrolling the Reels feed capturing screenshots of each unique video (by `src` hash).
6. Stores screenshots in `reels_screenshots/`.

## 5. Output

- Directory: `reels_screenshots/`
- Filenames: `reel_###_<hash>.png`
- Each file is a screenshot of the video element (fallback to full page if element-level capture fails).

## 6. Configuration Notes

- `REEL_TARGET`: Upper bound; loop may stop early if feed stagnates (no new reels after several scrolls or 60s inactivity).
- `CAPTURE=0`: Leaves the browser open on the Reels page so you can browse manually.
- `CHROME_AUTOMATION_DIR`: Use a writable path; if you see a Chrome warning about the directory, pick a new empty folder.
- 2FA: The script will pause waiting; finish verification manually, then it resumes.
- If you want headless mode you can add manually in code (`options.add_argument("--headless=new")`) but video elements may not load reliably headless.

## 7. Troubleshooting

| Issue | Cause | Fix |
|-------|-------|-----|
| Stuck on login page | Elements not found or challenge page | Complete challenge/2FA manually then rerun or let script wait. |
| No screenshots saved | `CAPTURE` disabled or zero target | Ensure `$env:CAPTURE` is `1` and `REEL_TARGET` > 0. |
| Chrome says can't read/write profile | Folder locked or permission issue | Point `CHROME_AUTOMATION_DIR` to a clean, user‑writable directory. |
| Many duplicates skipped | Same reel served repeatedly | Scroll further manually or increase wait; algorithm might be looping a small set. |

## 8. Safe Exit

Press `Ctrl + C` in the terminal if you need to abort; Chrome window will stay until Python exits. You can add try/finally around the main loop if you want guaranteed `driver.quit()` on interrupt.

## 9. Optional Enhancements (Not Implemented Yet)

- Metadata JSON (timestamp, reel URL) alongside screenshots.
- Headless + mTLS / proxy support.
- Automatic challenge / 2FA code prompt integration.
- Hash-based duplicate filter including frame sampling for identical content with different URLs.

## 10. Minimal Requirements File (optional)

Create `requirements.txt` if you want reproducibility:

```
selenium>=4.21.0
```

Then install with `pip install -r requirements.txt`.

---
Feel free to edit the script for logging or additional data extraction (captions, audio, etc.).
