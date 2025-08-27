import os, time, json, hashlib, random, urllib.parse
from datetime import datetime
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.webdriver.common.keys import Keys
from selenium.common.exceptions import TimeoutException, WebDriverException
from selenium.webdriver.chrome.options import Options

# ================= Config =================
OUT_DIR = os.environ.get("YT_OUT_DIR", "youtube_videos")
SEARCH_TERMS = [t.strip() for t in os.environ.get("YT_SEARCH_TERMS", "").split(',') if t.strip()]
PER_TERM = int(os.environ.get("YT_PER_TERM", "40"))  # videos per search term
SCROLL_PAUSE = float(os.environ.get("YT_SCROLL_PAUSE", "1.4"))
JITTER_MIN = float(os.environ.get("YT_JITTER_MIN", "1.2"))
JITTER_MAX = float(os.environ.get("YT_JITTER_MAX", "2.8"))
HEADLESS = os.environ.get("HEADLESS", "").lower() in {"1","true","yes"}
ATTACH = os.environ.get("ATTACH_EXISTING", "").lower() in {"1","true","yes"}
INCLUDE_SHORTS = os.environ.get("YT_INCLUDE_SHORTS", "0").lower() in {"1","true","yes"}
STOP_EMPTY_SCROLLS = int(os.environ.get("YT_STOP_EMPTY_SCROLLS", "12"))

os.makedirs(OUT_DIR, exist_ok=True)
META_PATH = os.path.join(OUT_DIR, "metadata.jsonl")

# ================= Driver =================

def build_driver():
    opts = Options()
    if ATTACH:
        opts.debugger_address = os.environ.get("DEBUG_ADDRESS", "127.0.0.1:9222")
    else:
        automation_dir = os.environ.get(
            "CHROME_AUTOMATION_DIR",
            os.path.join(os.getcwd(), "chrome_automation_profile")
        )
        os.makedirs(automation_dir, exist_ok=True)
        opts.add_argument(f"--user-data-dir={automation_dir}")
        profile_dir = os.environ.get("CHROME_PROFILE_DIR", "Default")
        opts.add_argument(f"--profile-directory={profile_dir}")
        opts.add_argument("--disable-blink-features=AutomationControlled")
        if HEADLESS:
            opts.add_argument("--headless=new")
        opts.add_experimental_option('excludeSwitches', ['enable-logging'])
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
    driver = webdriver.Chrome(options=opts)
    try:
        driver.maximize_window()
    except Exception:
        pass
    return driver

# ================= Helpers =================

def jitter_sleep(base: float = 0.0):
    time.sleep(base + random.uniform(JITTER_MIN, JITTER_MAX))

def video_identity(renderer):
    try:
        link = renderer.find_element(By.CSS_SELECTOR, "a#thumbnail")
        href = link.get_attribute("href") or ""
        vid = ""
        if "watch?v=" in href:
            q = urllib.parse.urlparse(href).query
            params = urllib.parse.parse_qs(q)
            if 'v' in params:
                vid = params['v'][0]
        if not vid and href:
            # fallback: hash entire href
            vid = hashlib.sha1(href.encode()).hexdigest()[:16]
        return vid or hashlib.sha1(link.get_attribute('outerHTML').encode()).hexdigest()[:16]
    except Exception:
        return hashlib.sha1(str(id(renderer)).encode()).hexdigest()[:16]

def extract_video(renderer):
    data = {}
    try:
        title_el = renderer.find_element(By.CSS_SELECTOR, "a#video-title")
        data['title'] = title_el.text.strip()
        data['url'] = title_el.get_attribute('href')
    except Exception:
        data['title'] = ''
        data['url'] = ''
    try:
        channel = renderer.find_element(By.CSS_SELECTOR, "ytd-channel-name #text").text.strip()
        data['channel'] = channel
    except Exception:
        data['channel'] = ''
    # Metadata line (views & age) usually inside span.inline-metadata-item
    try:
        meta_spans = renderer.find_elements(By.CSS_SELECTOR, "div#metadata-line span")
        metas = [s.text.strip() for s in meta_spans if s.text.strip()]
        # Heuristic: views first, age second
        if metas:
            data['views'] = metas[0] if len(metas) > 0 else ''
            data['published'] = metas[1] if len(metas) > 1 else ''
        else:
            data['views'] = data['published'] = ''
    except Exception:
        data['views'] = data['published'] = ''
    # Thumbnail alt text (sometimes holds extra info)
    try:
        alt = renderer.find_element(By.CSS_SELECTOR, "a#thumbnail img").get_attribute("alt")
        data['thumb_alt'] = alt
    except Exception:
        data['thumb_alt'] = ''
    return data

def save_screenshot(driver, renderer, term_slug, idx, vid):
    fname = os.path.join(OUT_DIR, f"yt_{term_slug}_{idx:03d}_{vid[:8]}.png")
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center'});", renderer)
        time.sleep(random.uniform(0.4, 0.9))
        renderer.screenshot(fname)
    except Exception:
        driver.save_screenshot(fname)
    return fname

# ================= Main scraping =================

def scrape():
    if not SEARCH_TERMS:
        print("[ERROR] Set YT_SEARCH_TERMS environment variable (comma-separated keywords).")
        return
    driver = build_driver()
    try:
        wait = WebDriverWait(driver, 25)
        with open(META_PATH, 'a', encoding='utf-8') as meta_file:
            for term in SEARCH_TERMS:
                encoded = urllib.parse.quote(term)
                search_url = f"https://www.youtube.com/results?search_query={encoded}"
                print(f"[TERM] {term} -> {search_url}")
                driver.get(search_url)
                try:
                    wait.until(EC.presence_of_element_located((By.CSS_SELECTOR, "ytd-video-renderer")))
                except TimeoutException:
                    print(f"[WARN] No video renderers visible for term {term}")
                collected = 0
                seen_ids = set()
                stagnant = 0
                last_height = 0
                term_slug = ''.join(ch for ch in term if ch.isalnum() or ch in ('_','#')).strip('#') or 'term'
                while collected < PER_TERM and stagnant < STOP_EMPTY_SCROLLS:
                    renderers = driver.find_elements(By.CSS_SELECTOR, "ytd-video-renderer")
                    new_in_cycle = 0
                    for r in renderers:
                        # Filter shorts if disabled
                        try:
                            href = r.find_element(By.CSS_SELECTOR, "a#thumbnail").get_attribute('href') or ''
                            if (not INCLUDE_SHORTS) and '/shorts/' in href:
                                continue
                            if 'live' in href and 'v=' not in href:
                                # skip non-standard live placeholder
                                continue
                        except Exception:
                            pass
                        vid = video_identity(r)
                        if vid in seen_ids:
                            continue
                        data = extract_video(r)
                        if not data.get('title'):  # skip empty
                            continue
                        seen_ids.add(vid)
                        shot = save_screenshot(driver, r, term_slug, collected, vid)
                        record = {
                            'mode': 'SEARCH',
                            'search_term': term,
                            'index': collected,
                            'video_id': vid,
                            'screenshot': shot,
                            'captured_at': datetime.utcnow().isoformat(),
                            **data
                        }
                        meta_file.write(json.dumps(record, ensure_ascii=False) + '\n')
                        meta_file.flush()
                        collected += 1
                        new_in_cycle += 1
                        print(f"[VIDEO:{term}] {collected}/{PER_TERM} {data['title'][:60]} -> {shot}")
                        if collected >= PER_TERM:
                            break
                    if collected >= PER_TERM:
                        break
                    # Scroll to load more
                    driver.find_element(By.TAG_NAME, 'body').send_keys(Keys.END)
                    jitter_sleep(SCROLL_PAUSE)
                    new_height = driver.execute_script('return document.documentElement.scrollHeight')
                    if new_in_cycle == 0:
                        stagnant += 1
                    else:
                        stagnant = 0
                    if new_height == last_height:
                        stagnant += 1
                    last_height = new_height
                print(f"[DONE] Term '{term}' collected {collected} videos.")
    finally:
        try:
            driver.quit()
        except Exception:
            pass

if __name__ == '__main__':
    scrape()
