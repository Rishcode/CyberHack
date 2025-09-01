from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.common.keys import Keys
import time, os, sys, hashlib, json
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

INTERACTIVE = os.environ.get("INSTA_INTERACTIVE", "1").lower() in {"1","true","yes"}
RAW_FILTER = os.environ.get("INSTA_FILTER_TERMS", "").strip()
FILTER_TERMS = [t.lower().strip() for t in RAW_FILTER.split(',') if t.strip()]
HASHTAG = os.environ.get("INSTA_HASHTAG", "").lstrip('#').strip()

def prompt_filter_terms():
    global FILTER_TERMS, HASHTAG
    if not FILTER_TERMS and INTERACTIVE:
        try:
            ans = input("Enter comma-separated keyword filters for reels (blank = all): ").strip()
            if ans:
                FILTER_TERMS = [a.lower().strip() for a in ans.split(',') if a.strip()]
        except EOFError:
            pass
    if not HASHTAG and INTERACTIVE:
        try:
            h = input("Enter a hashtag to open (without #, blank = generic Reels): ").strip().lstrip('#')
            if h:
                HASHTAG = h
        except EOFError:
            pass

prompt_filter_terms()

start_url = f"https://www.instagram.com/explore/tags/{HASHTAG}/" if HASHTAG else "https://www.instagram.com/reels/"
print(f"[STEP] Opening Instagram {'hashtag #' + HASHTAG if HASHTAG else 'Reels'} page...")
driver.get(start_url)
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
            driver.get(start_url)
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
                    driver.get(start_url)
                    time.sleep(3)
                    print("[INFO] Manual login detected.")
                    return
                time.sleep(3)
            print("[ERROR] Manual login not completed.")
            driver.quit(); sys.exit(1)
    else:
        driver.get(start_url)
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
FLAGGED_DIR = os.environ.get("INSTA_FLAGGED_DIR", os.path.join(out_dir, "flagged"))
os.makedirs(FLAGGED_DIR, exist_ok=True)
META_PATH = os.path.join(out_dir, "metadata.jsonl")
FLAGGED_META_PATH = os.path.join(FLAGGED_DIR, "flagged_metadata.jsonl")

USE_GEM_VISION = os.environ.get("USE_GEMINI_VISION", "1").lower() in {"1","true","yes"}
ONLY_FLAGGED = os.environ.get('ONLY_FLAGGED', os.environ.get('HATE_ONLY','0')).lower() in {'1','true','yes'}
GEM_FLAGS = {"deepfake","anti_india","dangerous","not_kid_safe"}
_DEBUG_DETECT = os.environ.get("DEBUG_DETECT", "0").lower() in {"1","true","yes"}
try:
    from gemini_vision import classify_image as gemini_vision_classify  # type: ignore
except Exception:
    gemini_vision_classify = None  # type: ignore
print(f"[INFO] Saving up to {target} reel screenshots in {out_dir}")
if FILTER_TERMS:
    print(f"[INFO] Filtering reels containing any of: {FILTER_TERMS}")
if HASHTAG:
    print(f"[INFO] Hashtag mode active: #{HASHTAG}")

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
    time.sleep(2.5)
    rid = reel_identity(video_el)
    fname = os.path.join(out_dir, f"reel_{idx:03d}_{rid[:8]}.png")
    # Element-level screenshot (preferred). Fallback to full page if fails.
    try:
        video_el.screenshot(fname)
    except Exception:
        driver.save_screenshot(fname)
    print(f"[CAPTURE] {fname}")
    return fname

def capture_hashtag_posts():
    hash_target = int(os.environ.get("INSTA_HASHTAG_TARGET", str(target)))
    print(f"[STEP] Capturing up to {hash_target} posts for #{HASHTAG} before reels...")
    seen_posts = set()
    collected = 0
    stagnant = 0
    max_stagnant = 10
    last_height = 0
    while collected < hash_target and stagnant < max_stagnant:
        # Hashtag pages often have anchors linking to /p/ or /reel/
        anchors = driver.find_elements(By.XPATH, "//a[contains(@href,'/p/') or contains(@href,'/reel/')]")
        new_in_cycle = 0
        for a in anchors:
            try:
                href = a.get_attribute('href') or ''
                if not href or href in seen_posts:
                    continue
                seen_posts.add(href)
                # Filter terms if provided (checking aria-label/text of parent)
                if FILTER_TERMS:
                    context_txt = ''
                    try:
                        context_txt = a.get_attribute('aria-label') or ''
                    except Exception:
                        pass
                    if context_txt:
                        ctx_low = context_txt.lower()
                        if not any(ft in ctx_low for ft in FILTER_TERMS):
                            continue
                pid = hashlib.sha1(href.encode()).hexdigest()
                fname = os.path.join(out_dir, f"hashtag_{collected:03d}_{pid[:8]}.png")
                try:
                    driver.execute_script("arguments[0].scrollIntoView({block:'center'});", a)
                    time.sleep(1.0)
                    a.screenshot(fname)
                except Exception:
                    driver.save_screenshot(fname)
                print(f"[HASHPOST] {collected+1}/{hash_target} -> {fname}")
                collected += 1
                new_in_cycle += 1
                if collected >= hash_target:
                    break
            except Exception:
                continue
        if collected >= hash_target:
            break
        # Scroll grid page
        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.END)
        time.sleep(1.8)
        new_height = driver.execute_script('return document.body.scrollHeight')
        if new_in_cycle == 0:
            stagnant += 1
        else:
            stagnant = 0
        if new_height == last_height:
            stagnant += 1
        last_height = new_height
    print(f"[DONE] Hashtag posts captured: {collected}")

# If hashtag provided, capture posts first then switch to reels feed for video collection
if HASHTAG:
    capture_hashtag_posts()
    print("[STEP] Switching to Reels feed after hashtag posts...")
    try:
        driver.get("https://www.instagram.com/reels/")
        time.sleep(3)
    except Exception:
        pass

print("[STEP] Starting scroll & capture loop for reels...")

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
            if FILTER_TERMS:
                context_txt = ""
                try:
                    # Try parent containers for text/captions
                    parent = v.find_element(By.XPATH, "ancestor::div[1]")  # keep minimal; adjust if needed
                    context_txt = parent.text.lower()
                except Exception:
                    pass
                if context_txt and not any(ft in context_txt for ft in FILTER_TERMS):
                    continue
            shot_path = center_and_capture(v, saved)
            # Optional Gemini Vision classification
            flagged = False
            gem_reason = ''
            gem_result = None
            if USE_GEM_VISION and gemini_vision_classify:
                # Basic context attempt: parent text
                context_txt = ''
                try:
                    parent = v.find_element(By.XPATH, "ancestor::div[1]")
                    context_txt = parent.text[:800]
                except Exception:
                    pass
                gem_result = gemini_vision_classify(shot_path, context_txt)
                if gem_result:
                    # Decide flag
                    if any(gem_result.get(k) for k in GEM_FLAGS):
                        flagged = True
                        reasons = [k for k in GEM_FLAGS if gem_result.get(k)]
                        gem_reason = "gemini_vision:" + ",".join(reasons) + (":" + gem_result.get('reason','') if gem_result.get('reason') else '')
                        if _DEBUG_DETECT:
                            print(f"[VISION_FLAG] {gem_reason}")
                    elif _DEBUG_DETECT:
                        print("[VISION_CLEAN]", gem_result)
            meta = {
                'id': rid,
                'index': saved,
                'screenshot': shot_path,
                'captured_at': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
                'context_terms': FILTER_TERMS,
            }
            if gem_result:
                meta.update(gem_result)
            if flagged:
                meta['flag_reason'] = gem_reason
                try:
                    import shutil
                    base = os.path.basename(shot_path)
                    flagged_path = os.path.join(FLAGGED_DIR, base)
                    if os.path.abspath(os.path.dirname(shot_path)) != os.path.abspath(FLAGGED_DIR):
                        if ONLY_FLAGGED:
                            shutil.move(shot_path, flagged_path)
                            meta['screenshot'] = flagged_path
                        else:
                            shutil.copy2(shot_path, flagged_path)
                except Exception:
                    pass
                with open(FLAGGED_META_PATH, 'a', encoding='utf-8') as f:
                    f.write(json.dumps(meta, ensure_ascii=False) + "\n")
                print(f"[FLAGGED] {gem_reason} -> {meta['screenshot']}")
            else:
                if ONLY_FLAGGED:
                    try: os.remove(shot_path)
                    except Exception: pass
                else:
                    with open(META_PATH, 'a', encoding='utf-8') as f:
                        f.write(json.dumps(meta, ensure_ascii=False) + "\n")
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
    time.sleep(3.5)


    # If feed stuck >60s without new reel break
    if time.time() - last_new_time > 60:
        print("[INFO] Stagnation timeout reached.")
        break

print(f"[DONE] Captured {saved} reel(s). Quitting.")
driver.quit()