from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time, os
import sys
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

# --- Path to your Chrome user profile ---
# Windows Example:
chrome_profile_path = r"C:\Users\Asus\AppData\Local\Google\Chrome\User Data"
# Linux Example:
# chrome_profile_path = "/home/<YourUsername>/.config/google-chrome"
# Mac Example:
# chrome_profile_path = "/Users/<YourUsername>/Library/Application Support/Google/Chrome"

options = webdriver.ChromeOptions()
options.add_argument(f"user-data-dir={chrome_profile_path}")

# Use a dedicated automation user-data-dir to avoid Chrome's 'cannot read/write to its data directory' warning
# (which happens if the directory is locked by an existing instance). Override via CHROME_AUTOMATION_DIR.
automation_dir = os.environ.get(
    "CHROME_AUTOMATION_DIR",
    os.path.join(os.getcwd(), "chrome_automation_profile")
)
os.makedirs(automation_dir, exist_ok=True)
options.add_argument(f"--user-data-dir={automation_dir}")

# Allow selecting a profile subfolder name inside automation dir (normally 'Default')
profile_dir = os.environ.get("CHROME_PROFILE_DIR", "Default")
options.add_argument(f"--profile-directory={profile_dir}")

options.add_argument("--disable-blink-features=AutomationControlled")

print("[INFO] Launching Chrome using your existing profile...")
driver = webdriver.Chrome(options=options)
try:
    driver.maximize_window()
except Exception:
    pass

print("[STEP] Opening Instagram Reels page...")
driver.get("https://www.instagram.com/reels/")

WAIT = WebDriverWait(driver, 25)

ENV_USER = "INSTA_USERNAME"
ENV_PASS = "INSTA_PASSWORD"

def get_env(name: str) -> str:
    v = os.environ.get(name, "").strip()
    if not v:
        raise RuntimeError(f"Missing environment variable {name}")
    return v

def dismiss_cookies():
    # Click common cookie consent buttons if present
    texts = [
        "Allow all",
        "Accept All",
        "Only allow essential cookies",
        "Accept",
        "Allow"
    ]
    for t in texts:
        try:
            btn = driver.find_element(By.XPATH, f"//button[contains(translate(., 'ABCDEFGHIJKLMNOPQRSTUVWXYZ', 'abcdefghijklmnopqrstuvwxyz'), '{t.lower()}')]")
            btn.click()
            print(f"[INFO] Cookie dialog accepted via '{t}'.")
            return
        except NoSuchElementException:
            continue
        except WebDriverException:
            continue

def on_login_page() -> bool:
    url = driver.current_url.lower()
    if "accounts/login" in url:
        return True
    # Also detect presence of username input
    try:
        driver.find_element(By.NAME, "username")
        driver.find_element(By.NAME, "password")
        return True
    except NoSuchElementException:
        return False

def has_session_cookie() -> bool:
    try:
        return any(c['name'] == 'sessionid' and c.get('value') for c in driver.get_cookies())
    except WebDriverException:
        return False

def perform_login():
    try:
        username = get_env(ENV_USER)
        password = get_env(ENV_PASS)
    except RuntimeError as e:
        print(f"[WARN] {e}. Cannot auto-login; please login manually.")
        return False
    print("[STEP] Performing automatic Instagram login...")

    # Always navigate explicitly to login page to avoid partial loads
    if not on_login_page():
        driver.get("https://www.instagram.com/accounts/login/")
        time.sleep(2)
    dismiss_cookies()

    try:
        user_input = WAIT.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='username']")))
        pass_input = WAIT.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='password']")))
    except TimeoutException:
        print("[ERROR] Login inputs not found (layout/change).")
        return False

    user_input.clear(); user_input.send_keys(username)
    time.sleep(0.4)
    pass_input.clear(); pass_input.send_keys(password)
    time.sleep(0.4)

    # Click the submit button to reduce detection
    try:
        login_btn = driver.find_element(By.XPATH, "//button[@type='submit' and not(@disabled)]")
        login_btn.click()
    except NoSuchElementException:
        pass_input.send_keys("\n")

    # Monitor post-login state
    start = time.time()
    error_detected = False
    while time.time() - start < 65:
        cur = driver.current_url.lower()
        if any(k in cur for k in ["challenge", "two_factor", "verification"]):
            print("[WARN] 2FA / challenge page encountered; manual action needed.")
            return False
        if has_session_cookie() and not on_login_page():
            print("[INFO] Session cookie present; login success.")
            # Navigate to reels after login
            driver.get("https://www.instagram.com/reels/")
            time.sleep(3)
            return True
        # Detect form error messages
        try:
            err = driver.find_element(By.XPATH, "//p[contains(@id,'slfErrorAlert') or contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'password')]")
            if err.text and not error_detected:
                print(f"[ERROR] Login error: {err.text.strip()}")
                error_detected = True
        except NoSuchElementException:
            pass
        time.sleep(2)

    print("[WARN] Login not confirmed within timeout; continuing.")
    return False

def ensure_logged_in():
    # If already seeing reels content, skip
    if "reels" in driver.current_url.lower() and has_session_cookie():
        return  # Already logged in
    # If not, maybe redirected to login
    if on_login_page():
        dismiss_cookies()
        if not perform_login():
            # Allow manual login fallback
            print("[INFO] Waiting up to 2 minutes for manual login...")
            start = time.time()
            while time.time() - start < 120:
                if "reels" in driver.current_url.lower() and has_session_cookie():
                    print("[INFO] Manual login detected.")
                    return
                time.sleep(3)
            print("[ERROR] Manual login not completed in time.")
            driver.quit(); sys.exit(1)
    else:
        # Not on login page but also not on reels - navigate directly
        driver.get("https://www.instagram.com/reels/")
        time.sleep(3)
        if on_login_page():
            ensure_logged_in()

ensure_logged_in()

if os.environ.get("CAPTURE", "1") not in {"1","true","yes"}:
    print("[INFO] CAPTURE disabled; leaving browser open on Reels page.")
    sys.exit(0)

# --- Create folder for screenshots ---
if not os.path.exists("reels_screenshots"):
    os.makedirs("reels_screenshots")
    print("[INFO] Created reels_screenshots directory")

# --- Scroll & capture reels ---
reel_count = 0
last_height = driver.execute_script("return document.body.scrollHeight")

while reel_count < 20:  # number of reels to capture
    reels = driver.find_elements(By.XPATH, '//article//video')
    
    for reel in reels:
        try:
            driver.execute_script("arguments[0].scrollIntoView();", reel)
            time.sleep(2)
            filename = f"reels_screenshots/reel_{reel_count}.png"
            driver.save_screenshot(filename)
            print(f"[CAPTURE] Saved {filename}")
            reel_count += 1
            if reel_count >= 20:
                break
        except Exception as e:
            print("Error:", e)

    # Scroll to load more reels
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
    time.sleep(3)
    
    new_height = driver.execute_script("return document.body.scrollHeight")
    if new_height == last_height:  # no more reels loaded
        break
    last_height = new_height

print(f"[DONE] Captured {reel_count} reels. Quitting.")
driver.quit()
