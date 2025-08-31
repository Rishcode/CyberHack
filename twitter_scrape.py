"""Twitter / X scraper with hate detection and Explore-based search.

Modes:
  TIMELINE  - Scroll home timeline
  TRENDING  - Capture trending topics
  SEARCH    - Open Explore, type each search term, press Enter, scrape results

Environment variables:
  TWITTER_USERNAME / TWITTER_PASSWORD  - credentials (unless attaching existing session)
  TW_MODE=TIMELINE|TRENDING|SEARCH
  TW_SEARCH_TERMS="term1,term2" (for SEARCH)
  TW_POST_TARGET=30  total posts per mode (per term for SEARCH)
  ONLY_FLAGGED=1 (store only flagged screenshots) or HATE_ONLY
  TAG_FILTERS="india,hate" (pre-detection tag filter)
  DEBUG_DETECT=1 enables verbose detection_model prints
  USE_GEMINI=1 enables Gemini fallback (requires GEMINI_API_KEY)
"""

from __future__ import annotations
import os, sys, time, json, random, hashlib
from datetime import datetime
from typing import Dict, Any
from detection_model import detect_content
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, NoSuchElementException, WebDriverException
from selenium.webdriver.common.keys import Keys
from selenium.webdriver.chrome.options import Options

# === Config ===
OUT_DIR = os.environ.get("TW_OUT_DIR", "twitter_posts")
TARGET_COUNT = int(os.environ.get("TW_POST_TARGET", "30"))
SCROLL_PAUSE = float(os.environ.get("TW_SCROLL_PAUSE", "1.4"))
JITTER_MIN = float(os.environ.get("TW_JITTER_MIN", "1.8"))
JITTER_MAX = float(os.environ.get("TW_JITTER_MAX", "3.8"))
HEADLESS = os.environ.get("HEADLESS", "").lower() in {"1","true","yes"}
ATTACH = os.environ.get("ATTACH_EXISTING", "").lower() in {"1","true","yes"}
ENV_USER = "TWITTER_USERNAME"
ENV_PASS = "TWITTER_PASSWORD"
TIMELINE_URL = os.environ.get("TW_TIMELINE_URL", "https://x.com/home")
TRENDING_URL = os.environ.get("TW_TRENDING_URL", "https://x.com/explore/tabs/trending")
EXPLORE_URL = "https://x.com/explore"
MODE = os.environ.get("TW_MODE", "TIMELINE").upper()
SEARCH_TERMS = [t.strip() for t in os.environ.get("TW_SEARCH_TERMS", "").split(',') if t.strip()]
FILTER_TERMS_ENV = os.environ.get("TW_FILTER_TERMS", "").strip()
FILTER_TERMS = [t.lower().strip() for t in FILTER_TERMS_ENV.split(',') if t.strip()]
INTERACTIVE = os.environ.get("TW_INTERACTIVE", "1").lower() in {"1","true","yes"}
TAG_FILTERS = [t.strip().lower() for t in os.environ.get("TAG_FILTERS", "").split(',') if t.strip()]
FLAGGED_DIR = os.environ.get("FLAGGED_DIR", os.path.join(OUT_DIR, "flagged"))
FLAGGED_META_PATH = os.environ.get("FLAGGED_META_PATH", os.path.join(FLAGGED_DIR, "flagged_metadata.jsonl"))
SEARCH_SCROLL_LIMIT = int(os.environ.get("TW_SEARCH_SCROLL_LIMIT", "45"))
SEARCH_VIA = os.environ.get("TW_SEARCH_VIA", "AUTO").upper()  # EXPLORE | DIRECT | AUTO

os.makedirs(OUT_DIR, exist_ok=True)
os.makedirs(FLAGGED_DIR, exist_ok=True)
META_PATH = os.path.join(OUT_DIR, "metadata.jsonl")

def _env(name: str) -> str:
    v = os.environ.get(name, '').strip()
    if not v:
        raise RuntimeError(f"Missing env {name}")
    return v

def interactive_setup():
    global MODE, SEARCH_TERMS, TAG_FILTERS, TARGET_COUNT
    if not INTERACTIVE or not sys.stdin.isatty():
        return
    try:
        mi = input(f"Mode [{MODE}] (TIMELINE/TRENDING/SEARCH): ").strip().upper()
        if mi in {"TIMELINE","TRENDING","SEARCH"}:
            MODE = mi
        if MODE == "SEARCH" and not SEARCH_TERMS:
            st = input("Search terms (comma separated): ").strip()
            if st:
                SEARCH_TERMS[:] = [t.strip() for t in st.split(',') if t.strip()]
        if not TAG_FILTERS:
            tg = input("Tag filters (comma, blank none): ").strip().lower()
            if tg:
                TAG_FILTERS[:] = [t.strip() for t in tg.split(',') if t.strip()]
        tc = input(f"Target count [{TARGET_COUNT}]: ").strip()
        if tc.isdigit():
            TARGET_COUNT = int(tc)
    except (EOFError, KeyboardInterrupt):
        pass

def build_driver():
    options = Options()
    if ATTACH:
        options.debugger_address = os.environ.get("DEBUG_ADDRESS", "127.0.0.1:9222")
    else:
        automation_dir = os.environ.get("CHROME_AUTOMATION_DIR", os.path.join(os.getcwd(), "chrome_automation_profile"))
        os.makedirs(automation_dir, exist_ok=True)
        options.add_argument(f"--user-data-dir={automation_dir}")
        options.add_argument("--profile-directory=Default")
        options.add_argument("--disable-blink-features=AutomationControlled")
        if HEADLESS:
            options.add_argument("--headless=new")
        options.add_experimental_option('excludeSwitches', ['enable-logging'])
        options.add_argument("--no-sandbox")
        options.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=options)
    try: driver.maximize_window()
    except Exception: pass
    return driver

def login(driver):
    if ATTACH:
        return
    driver.get("https://x.com/login")
    time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
    wait = WebDriverWait(driver, 15)
    try:
        u = wait.until(EC.visibility_of_element_located((By.NAME, "text")))
        u.clear(); u.send_keys(_env(ENV_USER)); time.sleep(random.uniform(0.3,0.7)); u.send_keys(Keys.ENTER)
    except TimeoutException:
        print("[LOGIN] Username field not found (maybe already logged in)")
    time.sleep(random.uniform(JITTER_MIN, JITTER_MAX))
    # Password
    try:
        p = wait.until(EC.visibility_of_element_located((By.NAME, "password")))
        p.clear(); p.send_keys(_env(ENV_PASS)); time.sleep(random.uniform(0.3,0.6)); p.send_keys(Keys.ENTER)
    except TimeoutException:
        print("[LOGIN] Password field not found")
    # Wait for primary column
    try:
        WebDriverWait(driver, 15).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='primaryColumn']")))
        print("[LOGIN] Success")
    except TimeoutException:
        print("[LOGIN] Primary column not confirmed")

def post_identity(card):
    try:
        tid = card.get_attribute('data-testid') or ''
        outer = card.get_attribute('outerHTML') or ''
        return hashlib.sha1((tid[:40] + outer[:400]).encode()).hexdigest()
    except WebDriverException:
        return str(id(card))

def extract_post(card) -> Dict[str, Any]:
    data: Dict[str, Any] = {}
    # text
    try:
        parts = card.find_elements(By.XPATH, ".//div[@data-testid='tweetText']//span")
        data['text'] = " ".join(p.text for p in parts).strip()
    except Exception:
        data['text'] = ''
    # user
    try:
        data['user'] = card.find_element(By.XPATH, ".//div[@data-testid='User-Name']//span").text
    except Exception:
        data['user'] = ''
    # time
    try:
        data['timestamp'] = card.find_element(By.XPATH, ".//time").get_attribute("datetime")
    except Exception:
        data['timestamp'] = ''
    return data

def save_post_screenshot(driver, card, idx, pid):
    path = os.path.join(OUT_DIR, f"post_{idx:03d}_{pid[:8]}.png")
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", card)
        time.sleep(random.uniform(0.3,0.8))
        card.screenshot(path)
    except Exception:
        driver.save_screenshot(path)
    return path

def tagged_match(text: str) -> bool:
    if not TAG_FILTERS:
        return True
    low = (text or '').lower()
    return any(tag in low or f"#{tag}" in low for tag in TAG_FILTERS)

def jitter_sleep():
    time.sleep(SCROLL_PAUSE + random.uniform(JITTER_MIN, JITTER_MAX))

def save_tweet(meta: Dict[str, Any], shot_path: str | None, flagged: bool):
    only_flagged = os.environ.get('ONLY_FLAGGED', os.environ.get('HATE_ONLY','0')).lower() in {'1','true','yes'}
    # Ensure screenshot in flagged dir if flagged
    if flagged:
        meta_file_path = FLAGGED_META_PATH
    else:
        meta_file_path = META_PATH
    if flagged or not only_flagged:
        if shot_path and flagged:
            try:
                import shutil
                base = os.path.basename(shot_path)
                target = os.path.join(FLAGGED_DIR, base)
                if os.path.abspath(os.path.dirname(shot_path)) != os.path.abspath(FLAGGED_DIR):
                    if only_flagged:
                        shutil.move(shot_path, target)
                        meta['screenshot'] = target
                    else:
                        shutil.copy2(shot_path, target)
            except Exception:
                pass
        with open(meta_file_path, 'a', encoding='utf-8') as f:
            f.write(json.dumps(meta, ensure_ascii=False) + "\n")
        return True
    else:
        # not flagged & only_flagged -> delete shot
        if shot_path and os.path.exists(shot_path):
            try: os.remove(shot_path)
            except Exception: pass
        return False

def _direct_search_url(term: str) -> str:
    from urllib.parse import quote
    enc = quote(term)
    # live (latest) results; change &f=live to remove for Top
    return f"https://x.com/search?q={enc}&src=typed_query&f=live"

def open_explore_and_search(driver, wait, term: str) -> bool:
    """Attempt Explore-based interactive search; fallback to direct URL if needed.
    Honors SEARCH_VIA (EXPLORE|DIRECT|AUTO).
    """
    strategy = SEARCH_VIA
    if strategy not in {"EXPLORE","DIRECT","AUTO"}:
        strategy = "AUTO"

    def try_explore() -> bool:
        driver.get(EXPLORE_URL)
        # Multiple selector attempts
        selectors = [
            'input[data-testid="SearchBox_Search_Input"]',
            'div[role="search"] input',
            'input[placeholder*="Search"]',
        ]
        box = None
        end_time = time.time() + 12
        while time.time() < end_time and box is None:
            for sel in selectors:
                try:
                    box = driver.find_element(By.CSS_SELECTOR, sel)
                    if box:
                        break
                except Exception:
                    continue
            if not box:
                time.sleep(0.6)
        if not box:
            print(f"[SEARCH][EXPLORE] Could not find search input for term '{term}' (URL now {driver.current_url})")
            return False
        try:
            box.click(); box.clear(); box.send_keys(term); box.send_keys(Keys.ENTER)
        except Exception as e:
            print(f"[SEARCH][EXPLORE] Typing failed: {e}")
            return False
        # Wait for tweets OR fallback quick
        try:
            WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR,'article[data-testid="tweet"]')))
            print(f"[SEARCH][EXPLORE] Results loaded for '{term}'")
            return True
        except TimeoutException:
            print(f"[SEARCH][EXPLORE] No tweet articles detected for '{term}' (current URL {driver.current_url})")
            return False

    def do_direct() -> bool:
        url = _direct_search_url(term)
        driver.get(url)
        try:
            WebDriverWait(driver, 12).until(EC.presence_of_element_located((By.CSS_SELECTOR,'article[data-testid="tweet"]')))
            print(f"[SEARCH][DIRECT] Loaded results for '{term}'")
            return True
        except TimeoutException:
            print(f"[SEARCH][DIRECT] No results visible for '{term}' (URL {driver.current_url})")
            return False

    if strategy == "DIRECT":
        return do_direct()
    if strategy == "EXPLORE":
        return try_explore()
    # AUTO
    if try_explore():
        return True
    print("[SEARCH] Falling back to direct URL...")
    return do_direct()

def collect_search_results(driver, term: str, target: int):
    seen = set(); collected = 0; empty = 0
    only_flagged = os.environ.get('ONLY_FLAGGED', os.environ.get('HATE_ONLY','0')).lower() in {'1','true','yes'}
    while collected < target and empty < SEARCH_SCROLL_LIMIT:
        cards = driver.find_elements(By.CSS_SELECTOR, 'article[data-testid="tweet"]')
        new_round = 0
        for c in cards:
            pid = post_identity(c)
            if pid in seen: continue
            seen.add(pid)
            meta = extract_post(c)
            txt = meta.get('text','')
            # Search term presence heuristic
            if term.lower().lstrip('#') not in txt.lower():
                continue
            if FILTER_TERMS and not any(ft in txt.lower() for ft in FILTER_TERMS):
                continue
            if not tagged_match(txt):
                continue
            meta.update({
                'id': pid,
                'mode': 'SEARCH',
                'search_term': term,
                'index': collected,
                'captured_at': datetime.utcnow().isoformat()
            })
            shot = save_post_screenshot(driver, c, collected, pid)
            meta['screenshot'] = shot
            flag, reason, score = detect_content(txt, image_path=shot)
            if flag:
                meta['flag_reason'] = reason; meta['flag_score'] = score
            stored = save_tweet(meta, shot, flagged=flag)
            if stored:
                collected += 1; new_round += 1
                print(f"[SEARCH:{term}] {collected}/{target} {'FLAG' if flag else 'OK'} {reason if flag else ''}")
            if collected >= target: break
        if new_round == 0:
            empty += 1
        else:
            empty = 0
        if collected >= target: break
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        jitter_sleep()
    print(f"[SEARCH:{term}] Done collected={collected} empty_scrolls={empty}")
    return collected

def run_search_mode(driver):
    if not SEARCH_TERMS:
        print("[SEARCH] No terms provided (TW_SEARCH_TERMS)")
        return
    wait = WebDriverWait(driver, 20)
    total = 0
    for term in SEARCH_TERMS:
        if not open_explore_and_search(driver, wait, term):
            continue
        total += collect_search_results(driver, term, TARGET_COUNT)
    print(f"[SEARCH] Total collected across terms: {total}")

def run_trending(driver):
    driver.get(TRENDING_URL)
    wait = WebDriverWait(driver, 20)
    try:
        wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='trend']")))
    except TimeoutException:
        print("[TRENDING] No trend container found")
        return
    seen=set(); collected=0; rounds=0
    while collected < TARGET_COUNT and rounds < 12:
        cards = driver.find_elements(By.CSS_SELECTOR, "div[data-testid='trend']")
        for card in cards:
            try:
                spans=[s.text.strip() for s in card.find_elements(By.CSS_SELECTOR,'span') if s.text.strip()]
                if not spans: continue
                topic=spans[0]
                if topic in seen: continue
                seen.add(topic)
                pid = hashlib.sha1(topic.encode()).hexdigest()
                shot = os.path.join(OUT_DIR, f"trend_{collected:03d}_{pid[:8]}.png")
                try: card.screenshot(shot)
                except Exception: driver.save_screenshot(shot)
                info={
                    'mode':'TRENDING','topic':topic,'id':pid,'index':collected,
                    'screenshot':shot,'captured_at':datetime.utcnow().isoformat()
                }
                save_tweet(info, shot, flagged=False)
                collected+=1
                print(f"[TREND] {collected}/{TARGET_COUNT} {topic}")
                if collected>=TARGET_COUNT: break
            except Exception:
                continue
        if collected>=TARGET_COUNT: break
        driver.execute_script('window.scrollTo(0, document.body.scrollHeight);')
        jitter_sleep(); rounds+=1
    print(f"[TRENDING] Collected {collected}")

def run_timeline(driver):
    driver.get(TIMELINE_URL)
    try:
        WebDriverWait(driver, 20).until(EC.presence_of_element_located((By.CSS_SELECTOR, "div[data-testid='primaryColumn']")))
    except TimeoutException:
        print("[TIMELINE] Primary column not detected")
    seen=set(); collected=0; stagnant=0; last_height=0
    while collected < TARGET_COUNT and stagnant < 18:
        cards = driver.find_elements(By.XPATH, "//article[@data-testid='tweet']")
        new_round=0
        for c in cards:
            pid = post_identity(c)
            if pid in seen: continue
            seen.add(pid)
            meta = extract_post(c)
            txt = meta.get('text','')
            if FILTER_TERMS and not any(ft in txt.lower() for ft in FILTER_TERMS):
                continue
            if not tagged_match(txt):
                continue
            meta.update({'id':pid,'mode':'TIMELINE','index':collected,'captured_at':datetime.utcnow().isoformat()})
            shot = save_post_screenshot(driver, c, collected, pid)
            meta['screenshot']=shot
            flag, reason, score = detect_content(txt, image_path=shot)
            if flag:
                meta['flag_reason']=reason; meta['flag_score']=score
            stored = save_tweet(meta, shot, flagged=flag)
            if stored:
                collected+=1; new_round+=1
                print(f"[TIMELINE] {collected}/{TARGET_COUNT} {'FLAG' if flag else 'OK'} {reason if flag else ''}")
            if collected>=TARGET_COUNT: break
        if collected>=TARGET_COUNT: break
        driver.find_element(By.TAG_NAME,'body').send_keys(Keys.END)
        jitter_sleep()
        new_height = driver.execute_script('return document.body.scrollHeight')
        if new_round==0: stagnant+=1
        else: stagnant=0
        if new_height==last_height: stagnant+=1
        last_height=new_height
    print(f"[TIMELINE] Collected {collected}")

def scrape_posts():
    interactive_setup()
    driver = build_driver()
    try:
        login(driver)
        if MODE == 'SEARCH':
            run_search_mode(driver)
        elif MODE == 'TRENDING':
            run_trending(driver)
        else:
            run_timeline(driver)
    finally:
        try: driver.quit()
        except Exception: pass

if __name__ == '__main__':
    scrape_posts()
