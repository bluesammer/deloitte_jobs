#!/usr/bin/env python
# coding: utf-8

# In[2]:


import csv
import json
import os
import shutil
import subprocess
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.chrome.service import Service
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException, WebDriverException


RUN_MODE = os.getenv("RUN_MODE", "local").strip().lower()
if RUN_MODE not in ["local", "railway"]:
    RUN_MODE = "local"

BASE_URL = "https://careers.deloitte.ca/search/"

EXCLUDE_KEYWORDS = [
    "student",
    "first nations",
    "tax",
    "grad",
    "graduate",
    "accountant",
]

FRENCH_HINTS = [
    " ou ",
    "conseiller",
    "conseillère",
    "financier",
    "financière",
    "directeur",
    "directrice",
    "gestionnaire",
    "ingénieur",
    "analyste principal",
    "spécialiste",
    "chef",
    "français",
    "expérience",
    "stratégie",
    "données",
    "services-conseils",
]

LOCAL_DATA_DIR = Path(".")
RAILWAY_DATA_DIR = Path("./data")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()

MAX_EMPTY_PAGES = 2
PAGE_WAIT_SECONDS = 3
SELENIUM_WAIT_SECONDS = 25


def get_data_dir() -> Path:
    data_dir = RAILWAY_DATA_DIR if RUN_MODE == "railway" else LOCAL_DATA_DIR
    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


DATA_DIR = get_data_dir()
CSV_FILE = DATA_DIR / "deloitte_jobs.csv"
STATE_FILE = DATA_DIR / "seen_jobs.json"


def build_driver():
    opts = Options()

    if RUN_MODE == "local":
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(chrome_path):
            opts.binary_location = chrome_path

        opts.add_argument("--start-maximized")
        opts.add_argument("--disable-blink-features=AutomationControlled")

        try:
            print("Starting local Chrome")
            driver = webdriver.Chrome(options=opts)
            driver.set_page_load_timeout(60)
            return driver
        except WebDriverException as e:
            print(f"Failed to start local Chrome: {e}")
            raise

    chrome_bin = (
        shutil.which("chromium")
        or shutil.which("chromium-browser")
        or shutil.which("google-chrome")
        or shutil.which("google-chrome-stable")
    )
    chrome_driver = shutil.which("chromedriver")

    print(f"Chrome found at: {chrome_bin}")
    print(f"Driver found at: {chrome_driver}")

    if not chrome_bin:
        result = subprocess.run(
            ["find", "/usr", "-name", "chrom*", "-type", "f"],
            capture_output=True, text=True
        )
        print(f"Chrom* files on disk:\n{result.stdout or '(none found)'}")
        raise RuntimeError("Chrome binary not found — see above for installed files")

    if not chrome_driver:
        raise RuntimeError("chromedriver not found in PATH")

    opts.binary_location = chrome_bin
    opts.add_argument("--headless=new")
    opts.add_argument("--no-sandbox")
    opts.add_argument("--disable-dev-shm-usage")
    opts.add_argument("--disable-gpu")
    opts.add_argument("--window-size=1400,1800")
    opts.add_argument("--disable-blink-features=AutomationControlled")

    service = Service(chrome_driver)

    try:
        print("Starting Railway Chrome")
        driver = webdriver.Chrome(service=service, options=opts)
        driver.set_page_load_timeout(60)
        return driver
    except WebDriverException as e:
        print(f"Failed to start Railway Chrome: {e}")
        raise


def send_telegram_message(text: str):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        print("Telegram vars missing. Skipping send.")
        return

    url = f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage"
    payload = {
        "chat_id": TELEGRAM_CHAT_ID,
        "text": text,
        "disable_web_page_preview": True,
    }

    try:
        r = requests.post(url, data=payload, timeout=20)
        print(f"Telegram status: {r.status_code}")
        if r.status_code != 200:
            print(r.text[:500])
    except Exception as e:
        print(f"Telegram send failed: {e}")


def send_new_jobs_to_telegram(new_jobs):
    if not new_jobs:
        print("No new jobs to send to Telegram.")
        return

    chunks = []
    current = f"New Deloitte jobs found: {len(new_jobs)}\n\n"

    for job in new_jobs:
        line = f"{job['title']}\n{job['url']}\n\n"
        if len(current) + len(line) > 3500:
            chunks.append(current)
            current = "More Deloitte jobs:\n\n" + line
        else:
            current += line

    if current.strip():
        chunks.append(current)

    print(f"Sending {len(chunks)} Telegram message chunk(s)")
    for chunk in chunks:
        send_telegram_message(chunk)


def is_french_title(title: str) -> bool:
    t = f" {title.lower().strip()} "

    if any(hint in t for hint in FRENCH_HINTS):
        return True

    french_chars = "àâçéèêëîïôùûüÿœæ"
    if any(ch in t for ch in french_chars):
        return True

    return False


def should_keep_job(title: str) -> bool:
    if not title:
        return False

    t = title.lower().strip()

    if any(word in t for word in EXCLUDE_KEYWORDS):
        return False

    if is_french_title(title):
        return False

    return True


def load_seen_jobs():
    if not STATE_FILE.exists():
        print("No prior state file found. Starting fresh.")
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
            print(f"Loaded existing seen jobs: {len(data)}")
            return data
    except Exception as e:
        print(f"Failed to read {STATE_FILE}: {e}")
        return {}


def save_seen_jobs(jobs_dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs_dict, f, ensure_ascii=False, indent=2)
    print(f"Saved seen jobs state: {len(jobs_dict)}")


def save_csv(jobs):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "url"])
        for job in jobs:
            writer.writerow([job["title"], job["url"]])
    print(f"CSV saved: {CSV_FILE}")


def click_if_exists(driver, by, value, timeout=4):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
        driver.execute_script("arguments[0].click();", el)
        print(f"Clicked element: {value}")
        return True
    except Exception:
        return False


def handle_cookies(driver):
    clicked = False
    clicked = click_if_exists(driver, By.ID, "cookie-reject", 3) or clicked
    clicked = click_if_exists(driver, By.ID, "cookiemanagerrejectall", 2) or clicked
    clicked = click_if_exists(driver, By.ID, "cookie-accept", 2) or clicked
    clicked = click_if_exists(driver, By.ID, "cookiemanageracceptall", 2) or clicked

    if clicked:
        print("Cookie banner handled")
    else:
        print("No cookie action needed")


def open_page(driver, page_num):
    params = {
        "q": "",
        "locationsearch": "",
        "searchResultView": "LIST",
        "sortBy": "",
        "pageNumber": page_num,
    }
    url = BASE_URL + "?" + urlencode(params)

    print("=" * 70)
    print(f"Opening page {page_num}")
    print(url)

    driver.get(url)
    print(f"Loaded URL: {driver.current_url}")

    handle_cookies(driver)
    time.sleep(2)

    buttons = driver.find_elements(By.CSS_SELECTOR, "button[data-testid='submitJobSearchBtn']")
    print(f"Search buttons found: {len(buttons)}")

    for btn in buttons:
        try:
            driver.execute_script("arguments[0].click();", btn)
            print("Clicked submit search button")
            break
        except Exception:
            pass


def wait_for_job_links(driver, wait, page_num):
    candidates = [
        "a[data-job-id]",
        "a[data-testid='jobTitle']",
        "a[href*='/job/']",
    ]

    print("Waiting for job links...")

    for css in candidates:
        try:
            wait.until(EC.presence_of_all_elements_located((By.CSS_SELECTOR, css)))
            time.sleep(2)
            count = len(driver.find_elements(By.CSS_SELECTOR, css))
            print(f"Selector matched: {css}, count: {count}")
            if count > 0:
                return css
        except Exception:
            print(f"Selector did not match yet: {css}")

    debug_file = DATA_DIR / f"debug_rendered_page_{page_num}.html"
    try:
        debug_file.write_text(driver.page_source, encoding="utf-8")
        print(f"Saved debug rendered page: {debug_file}")
    except Exception as e:
        print(f"Failed to save debug rendered page: {e}")

    raise TimeoutException("No job links found")


def scrape_page(driver, css, seen_page_run):
    rows = []
    links = driver.find_elements(By.CSS_SELECTOR, css)
    print(f"Raw links found with selector {css}: {len(links)}")

    for a in links:
        try:
            href = (a.get_attribute("href") or "").strip()
            title = (a.text or "").strip()

            if href and "/job/" in href:
                if not title:
                    title = (a.get_attribute("title") or "").strip()

                if not should_keep_job(title):
                    continue

                key = (title, href)
                if key not in seen_page_run:
                    seen_page_run.add(key)
                    rows.append({
                        "title": title,
                        "url": href,
                    })
                    print(f"Added job: {title[:120]}")
        except Exception:
            pass

    print(f"Filtered jobs kept on this page: {len(rows)}")
    return rows


def run_scraper():
    driver = None

    try:
        driver = build_driver()
        wait = WebDriverWait(driver, SELENIUM_WAIT_SECONDS)

        seen_page_run = set()
        all_jobs = []

        page = 1
        empty_streak = 0

        while True:
            open_page(driver, page)

            try:
                css = wait_for_job_links(driver, wait, page)
            except TimeoutException:
                print(f"No job links found on page {page}")
                page_jobs = []
            else:
                time.sleep(PAGE_WAIT_SECONDS)
                page_jobs = scrape_page(driver, css, seen_page_run)

            print(f"Jobs found on page {page}: {len(page_jobs)}")

            if not page_jobs:
                empty_streak += 1
                print(f"Empty page streak: {empty_streak}")
            else:
                empty_streak = 0
                all_jobs.extend(page_jobs)
                print(f"Total jobs collected so far: {len(all_jobs)}")

            if empty_streak >= MAX_EMPTY_PAGES:
                print(f"Reached {MAX_EMPTY_PAGES} empty pages in a row. Stopping.")
                break

            page += 1

        print("=" * 70)
        print(f"Scrape complete. Total jobs collected: {len(all_jobs)}")
        return all_jobs

    finally:
        if driver is not None:
            try:
                driver.quit()
                print("Browser closed")
            except Exception:
                pass


def update_baseline_and_find_new(all_jobs):
    old_seen = load_seen_jobs()
    new_jobs = []

    for job in all_jobs:
        url = job["url"]
        title = job["title"]

        if url not in old_seen:
            new_jobs.append(job)

        old_seen[url] = title

    save_seen_jobs(old_seen)
    return new_jobs


def main():
    print("Starting container job")
    print(f"RUN_MODE: {RUN_MODE}")
    print(f"DATA_DIR: {DATA_DIR}")
    print(f"STATE_FILE: {STATE_FILE}")
    print(f"CSV_FILE: {CSV_FILE}")

    first_run = not STATE_FILE.exists()
    print(f"First run: {first_run}")

    all_jobs = run_scraper()

    print(f"TOTAL JOBS AFTER SCRAPE: {len(all_jobs)}")
    save_csv(all_jobs)

    new_jobs = update_baseline_and_find_new(all_jobs)
    print(f"NEW JOBS FOUND: {len(new_jobs)}")

    if first_run:
        print("First run detected. Baseline created. No Telegram alerts sent.")
    else:
        send_new_jobs_to_telegram(new_jobs)

    print("Run finished")


if __name__ == "__main__":
    main()


# In[ ]:





# In[2]:





# In[ ]:





# In[ ]:





# In[ ]:




