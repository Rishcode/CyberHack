import os, time, json, hashlib, random
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.keys import Keys

# === Config ===
OUT_DIR = os.environ.get("TW_OUT_DIR", "twitter_posts")
TARGET_COUNT = int(os.environ.get("TW_POST_TARGET", "30"))
SCROLL_PAUSE = float(os.environ.get("TW_SCROLL_PAUSE", "1.6"))  # base pause
JITTER_MIN = float(os.environ.get("TW_JITTER_MIN", "2"))  # requested 2-4 second delay range
JITTER_MAX = float(os.environ.get("TW_JITTER_MAX", "4"))
HEADLESS = os.environ.get("HEADLESS", "").lower() in {"1","true","yes"}
ATTACH = os.environ.get("ATTACH_EXISTING", "").lower() in {"1","true","yes"}
ENV_USER = "TWITTER_USERNAME"
ENV_PASS = "TWITTER_PASSWORD"
BASE_URL = "https://x.com/"  # formerly twitter.com
TIMELINE_URL = os.environ.get("TW_TIMELINE_URL", "https://x.com/home")
TRENDING_URL = os.environ.get("TW_TRENDING_URL", "https://x.com/explore/tabs/trending")
MODE = os.environ.get("TW_MODE", "TIMELINE").upper()  # TIMELINE | TRENDING | SEARCH
SEARCH_TERMS = [t.strip() for t in os.environ.get("TW_SEARCH_TERMS", "").split(',') if t.strip()]

os.makedirs(OUT_DIR, exist_ok=True)
meta_path = os.path.join(OUT_DIR, "metadata.jsonl")

# === Driver Setup ===
from selenium.webdriver.chrome.options import Options

def build_driver():
    options = Options()
    if ATTACH:
        options.debugger_address = os.environ.get("DEBUG_ADDRESS", "127.0.0.1:9222")
    else:
        # Mirror insta_final pattern: dedicated automation directory (not your live profile)
        automation_dir = os.environ.get(
            "CHROME_AUTOMATION_DIR",
            os.path.join(os.getcwd(), "chrome_automation_profile")
        )
        os.makedirs(automation_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={automation_dir}")
        profile_dir = os.environ.get("CHROME_PROFILE_DIR", "Default")
        options.add_argument(f"--profile-directory={profile_dir}")
        options.add_argument("--disable-blink-features=AutomationControlled")
        if HEADLESS:
            options.add_argument("--headless=new")
        # Keep logs quieter
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    try:
        driver.maximize_window()
    except Exception:
        pass
    return driver

# === Helpers ===

def _env(name:str)->str:
    v = os.environ.get(name, '').strip()
    if not v:
        raise RuntimeError(f"Missing environment variable {name}")
    return v

def login(driver):
    if ATTACH:
        # Assume already logged in when attaching
        return
    driver.get("https://x.com/login")
    time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
    wait = WebDriverWait(driver, 10)
    # Step 1: Username / email / phone
    try:
        user_in = wait.until(EC.visibility_of_element_located((By.NAME, "text")))
        user_in.clear()
        user_in.send_keys(_env(ENV_USER))
        time.sleep(random.uniform(0.25, 0.6))
        # Prefer pressing Enter instead of .submit() (field often not inside <form>)
        user_in.send_keys(Keys.ENTER)
    except TimeoutException:
        print("[WARN] Username field not found; maybe already logged in.")
    except WebDriverException as e:
        print(f"[WARN] Could not type username: {e}")

    # Some flows require clicking a Next button after username
    time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
    try:
        next_btn_candidates = driver.find_elements(By.XPATH, "//span[text()='Next' or text()='Next ']/ancestor::div[@role='button']")
        if next_btn_candidates:
            next_btn_candidates[0].click()
            time.sleep(1)
    except WebDriverException:
        pass

    # Step 2: Possible extra identifier challenge (e.g., phone/email confirm)
    try:
        if not driver.find_elements(By.NAME, "password"):
            challenge_input = driver.find_elements(By.NAME, "text")
            if challenge_input and (challenge_input[0].get_attribute('value') == '' or challenge_input[0].get_attribute('value') == _env(ENV_USER)):
                # Re-enter same identifier then Enter
                challenge_input[0].clear()
                challenge_input[0].send_keys(_env(ENV_USER))
                time.sleep(random.uniform(0.3, 0.7))
                challenge_input[0].send_keys(Keys.ENTER)
                time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
    except WebDriverException:
        pass

    # Step 3: Password
    try:
        pwd_in = WebDriverWait(driver, 10).until(EC.visibility_of_element_located((By.NAME, "password")))
        pwd_in.clear()
        pwd_in.send_keys(_env(ENV_PASS))
        time.sleep(random.uniform(0.25, 0.6))
        # Try clicking Log in button if present; else Enter
        login_btns = driver.find_elements(By.XPATH, "//span[text()='Log in' or text()='Log In']/ancestor::div[@role='button']")
        if login_btns:
            login_btns[0].click()
            time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
        else:
            pwd_in.send_keys(Keys.ENTER)
            time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
    except TimeoutException:
        print("[WARN] Password field not found; continuing.")
    except WebDriverException as e:
        print(f"[WARN] Could not enter password: {e}")
    # Wait for primary column
    try:
        WebDriverWait(driver, 10).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='primaryColumn']")))
        print("[INFO] Login success (primary column detected).")
    except TimeoutException:
        print("[WARN] Could not confirm login.")


def post_identity(card):
    try:
        # try data-testid= tweet element with stable attributes
        tid = card.get_attribute('data-testid')
        outer = card.get_attribute('outerHTML')
        h = hashlib.sha1((tid or '')[:32].encode()+ outer[:400].encode()).hexdigest()
        return h
    except WebDriverException:
        return str(id(card))


def extract_post(card):
    data = {}
    try:
        # Username / handle
        handle_el = card.find_element(By.CSS_SELECTOR, "a[href*='/status/']").find_element(By.XPATH, "./ancestor::article")
    except Exception:
        pass
    try:
        user = card.find_element(By.XPATH, ".//div[@data-testid='User-Name']//span").text
        data['user'] = user
    except Exception:
        data['user'] = ''
    # Content text
    try:
        text_parts = card.find_elements(By.XPATH, ".//div[@data-testid='tweetText']//span")
        data['text'] = " ".join([t.text for t in text_parts]).strip()
    except Exception:
        data['text'] = ''
    # Timestamp
    try:
        ts = card.find_element(By.XPATH, ".//time").get_attribute("datetime")
        data['timestamp'] = ts
    except Exception:
        data['timestamp'] = ''
    return data


def save_post_screenshot(driver, card, idx, pid):
    fname = os.path.join(OUT_DIR, f"post_{idx:03d}_{pid[:8]}.png")
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
        time.sleep(random.uniform(0.5, 1.1))
        card.screenshot(fname)
    except Exception:
        driver.save_screenshot(fname)
    return fname


def scrape_posts():
    driver = build_driver()
    try:
        login(driver)
        if MODE == "TRENDING":
            driver.get(TRENDING_URL)
            wait = WebDriverWait(driver, 30)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='trend']")))
            except TimeoutException:
                print('[ERROR] No trending elements found.')
                return
            trends_seen = set()
            collected = 0
            with open(meta_path, 'a', encoding='utf-8') as meta_file:
                scroll_rounds = 0
                while collected < TARGET_COUNT and scroll_rounds < 10:
                    trend_cards = driver.find_elements(By.CSS_SELECTOR, "div[data-testid='trend']")
                    for card in trend_cards:
                        try:
                            label_spans = card.find_elements(By.CSS_SELECTOR, "span")
                            texts = [s.text.strip() for s in label_spans if s.text.strip()]
                            if not texts:
                                continue
                            topic = texts[0]
                            if topic in trends_seen:
                                continue
                            trends_seen.add(topic)
                            # Optional count heuristics
                            count = ''
                            for t in texts[1:]:
                                if any(ch.isdigit() for ch in t) or 'posts' in t.lower() or 'tweets' in t.lower():
                                    count = t
                                    break
                            pid = hashlib.sha1(topic.encode()).hexdigest()
                            driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
                            time.sleep(random.uniform(0.5, 1.0))
                            shot_path = os.path.join(OUT_DIR, f"trend_{collected:03d}_{pid[:8]}.png")
                            try:
                                card.screenshot(shot_path)
                            except Exception:
                                driver.save_screenshot(shot_path)
                            info = {
                                'mode': 'TRENDING',
                                'topic': topic,
                                'count': count,
                                'id': pid,
                                'index': collected,
                                'screenshot': shot_path,
                                'captured_at': datetime.utcnow().isoformat()
                            }
                            meta_file.write(json.dumps(info, ensure_ascii=False) + "\n")
                            meta_file.flush()
                            print(f"[TREND] {collected+1}/{TARGET_COUNT} {topic} -> {shot_path}")
                            collected += 1
                            if collected >= TARGET_COUNT:
                                break
                        except Exception:
                            continue
                    if collected >= TARGET_COUNT:
                        break
                    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.END)
                    time.sleep(SCROLL_PAUSE + random.uniform(JITTER_MIN, JITTER_MAX))
                    scroll_rounds += 1
                print(f"[DONE] Collected {collected} trending topics.")
        elif MODE == "SEARCH":
            if not SEARCH_TERMS:
                print("[ERROR] SEARCH mode requires TW_SEARCH_TERMS env var (comma-separated keywords).")
                return
            wait = WebDriverWait(driver, 30)
            with open(meta_path, 'a', encoding='utf-8') as meta_file:
                for term in SEARCH_TERMS:
                    from urllib.parse import quote
                    encoded = quote(term)
                    # Using 'live' filter for latest; remove &f=live for Top
                    search_url = f"https://x.com/search?q={encoded}&src=typed_query&f=live"
                    print(f"[TERM] Searching: {term} -> {search_url}")
                    driver.get(search_url)
                    try:
                        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='primaryColumn']")))
                    except TimeoutException:
                        print(f"[WARN] Primary column not found for term {term}")
                    collected = 0
                    seen = set()
                    stagnant = 0
                    last_height = 0
                    term_slug = ''.join(ch for ch in term if ch.isalnum() or ch in ('_','#')).strip('#') or 'term'
                    target_per_term = TARGET_COUNT  # reuse global target; user can adjust env per run
                    while collected < target_per_term and stagnant < 12:
                        cards = driver.find_elements(By.XPATH, "//article[@data-testid='tweet']")
                        new_in_cycle = 0
                        for c in cards:
                            pid = post_identity(c)
                            if pid in seen:
                                continue
                            # crude filter: ensure term (case-insensitive) appears in text (or hashtag form) before saving
                            text_lower = ''
                            try:
                                text_parts = c.find_elements(By.XPATH, ".//div[@data-testid='tweetText']//span")
                                text_lower = ' '.join(t.text for t in text_parts).lower()
                            except Exception:
                                pass
                            search_variants = {term.lower()}
                            if term.startswith('#'):
                                search_variants.add(term.lower().lstrip('#'))
                            if not any(v in text_lower for v in search_variants):
                                # skip if term not present; remove this block to capture all results page tweets
                                continue
                            seen.add(pid)
                            info = extract_post(c)
                            info['id'] = pid
                            info['index'] = collected
                            info['search_term'] = term
                            info['mode'] = 'SEARCH'
                            info['captured_at'] = datetime.utcnow().isoformat()
                            shot_path = os.path.join(OUT_DIR, f"search_{term_slug}_{collected:03d}_{pid[:8]}.png")
                            try:
                                driver.execute_script("arguments[0].scrollIntoView({block:'center'});", c)
                                time.sleep(random.uniform(0.4, 0.9))
                                c.screenshot(shot_path)
                            except Exception:
                                driver.save_screenshot(shot_path)
                            info['screenshot'] = shot_path
                            meta_file.write(json.dumps(info, ensure_ascii=False) + "\n")
                            meta_file.flush()
                            collected += 1
                            new_in_cycle += 1
                            print(f"[SEARCH:{term}] {collected}/{target_per_term} -> {shot_path}")
                            if collected >= target_per_term:
                                break
                        if collected >= target_per_term:
                            break
                        driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.END)
                        time.sleep(SCROLL_PAUSE + random.uniform(JITTER_MIN, JITTER_MAX))
                        new_height = driver.execute_script('return document.body.scrollHeight')
                        if new_in_cycle == 0:
                            stagnant += 1
                        else:
                            stagnant = 0
                        if new_height == last_height:
                            stagnant += 1
                        last_height = new_height
                    print(f"[DONE] Term '{term}' collected {collected} tweets.")
        else:
            # TIMELINE mode (default)
            driver.get(TIMELINE_URL)
            wait = WebDriverWait(driver, 30)
            try:
                wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='primaryColumn']")))
            except TimeoutException:
                print('[WARN] Timeline primary column not detected.')

            collected = 0
            seen = set()
            with open(meta_path, 'a', encoding='utf-8') as meta_file:
                last_height = 0
                stagnant = 0
                while collected < TARGET_COUNT and stagnant < 15:
                    cards = driver.find_elements(By.XPATH, "//article[@data-testid='tweet']")
                    new_in_cycle = 0
                    for c in cards:
                        pid = post_identity(c)
                        if pid in seen:
                            continue
                        seen.add(pid)
                        info = extract_post(c)
                        info['id'] = pid
                        info['index'] = collected
                        info['captured_at'] = datetime.utcnow().isoformat()
                        shot = save_post_screenshot(driver, c, collected, pid)
                        info['screenshot'] = shot
                        meta_file.write(json.dumps(info, ensure_ascii=False) + "\n")
                        meta_file.flush()
                        print(f"[POST] {collected+1}/{TARGET_COUNT} saved -> {shot}")
                        collected += 1
                        new_in_cycle += 1
                        if collected >= TARGET_COUNT:
                            break
                    if collected >= TARGET_COUNT:
                        break
                    # Scroll
                    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.END)
                    # Base pause + human jitter
                    time.sleep(SCROLL_PAUSE + random.uniform(JITTER_MIN, JITTER_MAX))
                    new_height = driver.execute_script('return document.body.scrollHeight')
                    if new_in_cycle == 0:
                        stagnant += 1
                    else:
                        stagnant = 0
                    if new_height == last_height:
                        stagnant += 1
                    last_height = new_height
                print(f"[DONE] Collected {collected} posts.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == '__main__':
    scrape_posts()
