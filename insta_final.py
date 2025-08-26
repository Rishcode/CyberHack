from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time, os, sys, hashlib
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException

chrome_profile_path = r"C:\Users\Asus\AppData\Local\Google\Chrome\User Data"

options = webdriver.ChromeOptions()

automation_dir = os.environ.get(
    "CHROME_AUTOMATION_DIR",
    os.path.join(os.getcwd(), "chrome_automation_profile")
)
os.makedirs(automation_dir, exist_ok=True)
options.add_argument(f"--user-data-dir={automation_dir}")
profile_dir = os.environ.get("CHROME_PROFILE_DIR", "Default")
options.add_argument(f"--profile-directory={profile_dir}")
options.add_argument("--disable-blink-features=AutomationControlled")

print("[INFO] Launching Chrome...")
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
    texts = ["allow all", "accept all", "only allow essential", "accept", "allow"]
    for t in texts:
        try:
            btn = driver.find_element(By.XPATH, f"//button[contains(translate(.,'ABCDEFGHIJKLMNOPQRSTUVWXYZ','abcdefghijklmnopqrstuvwxyz'),'{t}')]")
            btn.click()
            print(f"[INFO] Cookie dialog accepted via '{t}'.")
            return
        except NoSuchElementException:
            continue
        except WebDriverException:
            continue

def on_login_page() -> bool:
    url = driver.current_url.lower()
    if "accounts/login" in url: return True
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
        print(f"[WARN] {e}. Manual login required.")
        return False
    print("[STEP] Performing automatic Instagram login...")
    if not on_login_page():
        driver.get("https://www.instagram.com/accounts/login/")
        time.sleep(2)
    dismiss_cookies()
    try:
        user_input = WAIT.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='username']")))
        pass_input = WAIT.until(EC.visibility_of_element_located((By.CSS_SELECTOR, "input[name='password']")))
    except TimeoutException:
        print("[ERROR] Login inputs not found.")
        return False
    user_input.clear(); user_input.send_keys(username)
    time.sleep(0.3)
    pass_input.clear(); pass_input.send_keys(password)
    time.sleep(0.3)
    try:
        driver.find_element(By.XPATH, "//button[@type='submit' and not(@disabled)]").click()
    except NoSuchElementException:
        pass_input.send_keys("\n")
    start = time.time()
    while time.time() - start < 60:
        if has_session_cookie() and not on_login_page():
            print("[INFO] Login success.")
            driver.get("https://www.instagram.com/reels/")
            time.sleep(3)
            return True
        if any(k in driver.current_url.lower() for k in ["challenge","two_factor","verification"]):
            print("[WARN] 2FA / challenge encountered.")
            return False
        time.sleep(2)
    print("[WARN] Login not confirmed (timeout).")
    return False

def ensure_logged_in():
    if "reels" in driver.current_url.lower() and has_session_cookie():
        return
    if on_login_page():
        dismiss_cookies()
        ok = perform_login()
        if not ok:
            print("[INFO] Waiting up to 120s for manual login...")
            start = time.time()
            while time.time() - start < 120:
                if has_session_cookie() and not on_login_page():
                    driver.get("https://www.instagram.com/reels/")
                    time.sleep(3)
                    print("[INFO] Manual login detected.")
                    return
                time.sleep(3)
            print("[ERROR] Manual login not completed.")
            driver.quit(); sys.exit(1)
    else:
        driver.get("https://www.instagram.com/reels/")
        time.sleep(3)
        if on_login_page():
            ensure_logged_in()

ensure_logged_in()

if os.environ.get("CAPTURE", "1").lower() not in {"1","true","yes"}:
    print("[INFO] CAPTURE disabled; leaving browser on Reels.")
    sys.exit(0)

target = int(os.environ.get("REEL_TARGET", "50"))
out_dir = "reels_screenshots"
os.makedirs(out_dir, exist_ok=True)
print(f"[INFO] Saving up to {target} reel screenshots in {out_dir}")

seen_ids = set()
saved = 0
stagnant_scrolls = 0
max_stagnant = 8
last_new_time = time.time()

def reel_identity(video_el):
    src = (video_el.get_attribute("src") or "").strip()
    if not src:
        # fall back to parent link
        try:
            link = video_el.find_element(By.XPATH, ".//ancestor::a[contains(@href,'/reel/')]")
            src = link.get_attribute("href")
        except Exception:
            src = str(id(video_el))
    return hashlib.sha1(src.encode("utf-8")).hexdigest()

def center_and_capture(video_el, idx):
    driver.execute_script("""
        const el = arguments[0];
        el.scrollIntoView({behavior:'auto', block:'center', inline:'center'});
    """, video_el)
    time.sleep(1.2)
    rid = reel_identity(video_el)
    fname = os.path.join(out_dir, f"reel_{idx:03d}_{rid[:8]}.png")
    # Element-level screenshot (preferred). Fallback to full page if fails.
    try:
        video_el.screenshot(fname)
    except Exception:
        driver.save_screenshot(fname)
    print(f"[CAPTURE] {fname}")

print("[STEP] Starting scroll & capture loop...")

while saved < target:
    # Collect candidate video elements
    videos = driver.find_elements(By.XPATH, "//video")
    new_in_cycle = 0
    for v in videos:
        try:
            rid = reel_identity(v)
            if rid in seen_ids:
                continue
            seen_ids.add(rid)
            center_and_capture(v, saved)
            saved += 1
            new_in_cycle += 1
            last_new_time = time.time()
            if saved >= target:
                break
        except Exception as e:
            print(f"[WARN] Capture error: {e}")
    if saved >= target:
        break
    if new_in_cycle == 0:
        stagnant_scrolls += 1
    else:
        stagnant_scrolls = 0
    if stagnant_scrolls >= max_stagnant:
        print("[INFO] No new reels after several scrolls; stopping.")
        break

    # Scroll down
    driver.find_element(By.TAG_NAME, "body").send_keys(Keys.END)
    time.sleep(2.2)

    # If feed stuck >60s without new reel break
    if time.time() - last_new_time > 60:
        print("[INFO] Stagnation timeout reached.")
        break

print(f"[DONE] Captured {saved} reel(s). Quitting.")
driver.quit()