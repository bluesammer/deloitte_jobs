#!/usr/bin/env python
# coding: utf-8

# In[3]:


import csv
import json
import os
import time
from pathlib import Path
from urllib.parse import urlencode

import requests
from selenium import webdriver
from selenium.webdriver.common.by import By
from selenium.webdriver.chrome.options import Options
from selenium.webdriver.support.ui import WebDriverWait
from selenium.webdriver.support import expected_conditions as EC
from selenium.common.exceptions import TimeoutException


# =========================
# CONFIG
# =========================

#RUN_MODE = "local"   # "local" or "railway"
RUN_MODE = os.getenv("RUN_MODE", "local").strip().lower()

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
PAGE_WAIT_SECONDS = 2
SELENIUM_WAIT_SECONDS = 20


# =========================
# PATHS
# =========================

def get_data_dir() -> Path:
    if RUN_MODE.lower() == "railway":
        data_dir = RAILWAY_DATA_DIR
    else:
        data_dir = LOCAL_DATA_DIR

    data_dir.mkdir(parents=True, exist_ok=True)
    return data_dir


DATA_DIR = get_data_dir()
CSV_FILE = DATA_DIR / "deloitte_jobs.csv"
STATE_FILE = DATA_DIR / "seen_jobs.json"


# =========================
# BROWSER SETUP
# =========================

def build_driver():
    opts = Options()

    if RUN_MODE.lower() == "local":
        chrome_path = r"C:\Program Files\Google\Chrome\Application\chrome.exe"
        if os.path.exists(chrome_path):
            opts.binary_location = chrome_path
        opts.add_argument("--start-maximized")
    else:
        opts.add_argument("--headless=new")
        opts.add_argument("--no-sandbox")
        opts.add_argument("--disable-dev-shm-usage")
        opts.add_argument("--disable-gpu")
        opts.add_argument("--window-size=1400,1800")

    driver = webdriver.Chrome(options=opts)
    return driver


# =========================
# TELEGRAM
# =========================

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
        print("No new jobs to send.")
        return

    chunks = []
    current = "New Deloitte jobs:\n\n"

    for job in new_jobs:
        line = f"{job['title']}\n{job['url']}\n\n"
        if len(current) + len(line) > 3500:
            chunks.append(current)
            current = "More Deloitte jobs:\n\n" + line
        else:
            current += line

    if current.strip():
        chunks.append(current)

    for chunk in chunks:
        send_telegram_message(chunk)


# =========================
# FILTERS
# =========================

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


# =========================
# FILE STORAGE
# =========================

def load_seen_jobs():
    if not STATE_FILE.exists():
        return {}

    try:
        with open(STATE_FILE, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception as e:
        print(f"Failed to read {STATE_FILE}: {e}")
        return {}


def save_seen_jobs(jobs_dict):
    with open(STATE_FILE, "w", encoding="utf-8") as f:
        json.dump(jobs_dict, f, ensure_ascii=False, indent=2)


def save_csv(jobs):
    with open(CSV_FILE, "w", newline="", encoding="utf-8-sig") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "url"])
        for job in jobs:
            writer.writerow([job["title"], job["url"]])


# =========================
# SELENIUM HELPERS
# =========================

def click_if_exists(driver, by, value, timeout=4):
    try:
        el = WebDriverWait(driver, timeout).until(
            EC.element_to_be_clickable((by, value))
        )
        driver.execute_script("arguments[0].click();", el)
        return True
    except Exception:
        return False


def handle_cookies(driver):
    click_if_exists(driver, By.ID, "cookie-reject", 3)
    click_if_exists(driver, By.ID, "cookiemanagerrejectall", 2)
    click_if_exists(driver, By.ID, "cookie-accept", 2)
    click_if_exists(driver, By.ID, "cookiemanageracceptall", 2)


def open_page(driver, page_num):
    params = {
        "q": "",
        "locationsearch": "",
        "searchResultView": "LIST",
        "sortBy": "",
        "pageNumber": page_num,
    }
    url = BASE_URL + "?" + urlencode(params)
    driver.get(url)
    handle_cookies(driver)

    buttons = driver.find_elements(By.CSS_SELECTOR, "button[data-testid='submitJobSearchBtn']")
    for btn in buttons:
        try:
            driver.execute_script("arguments[0].click();", btn)
            break
        except Exception:
            pass


def wait_for_job_links(driver, wait):
    candidates = [
        "a[href*='/job/']",
        "a[data-testid='jobTitle']",
    ]
    for css in candidates:
        try:
            wait.until(lambda d: len(d.find_elements(By.CSS_SELECTOR, css)) > 0)
            return css
        except Exception:
            pass
    raise TimeoutException("No job links found")


def scrape_page(driver, css, seen_page_run):
    rows = []
    links = driver.find_elements(By.CSS_SELECTOR, css)

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
        except Exception:
            pass

    return rows


# =========================
# MAIN SCRAPER
# =========================

def run_scraper():
    driver = build_driver()
    wait = WebDriverWait(driver, SELENIUM_WAIT_SECONDS)

    seen_page_run = set()
    all_jobs = []

    page = 1
    empty_streak = 0

    try:
        while True:
            print(f"\nOpening page {page}")
            open_page(driver, page)

            try:
                css = wait_for_job_links(driver, wait)
            except TimeoutException:
                print(f"No job links found on page {page}. Stopping.")
                break

            time.sleep(PAGE_WAIT_SECONDS)
            page_jobs = scrape_page(driver, css, seen_page_run)

            if not page_jobs:
                empty_streak += 1
                print(f"Page {page} had 0 filtered jobs")
            else:
                empty_streak = 0
                all_jobs.extend(page_jobs)
                print(f"Page {page}: {len(page_jobs)} filtered jobs, total {len(all_jobs)}")

            if empty_streak >= MAX_EMPTY_PAGES:
                print("Two empty pages in a row. Stopping.")
                break

            page += 1

    finally:
        driver.quit()

    return all_jobs


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
    print(f"RUN_MODE: {RUN_MODE}")
    print(f"DATA_DIR: {DATA_DIR}")

    all_jobs = run_scraper()

    save_csv(all_jobs)
    print(f"\nSaved {len(all_jobs)} filtered jobs to {CSV_FILE}")

    new_jobs = update_baseline_and_find_new(all_jobs)
    print(f"New jobs found this run: {len(new_jobs)}")

    send_new_jobs_to_telegram(new_jobs)


if __name__ == "__main__":
    main()


# In[2]:





# In[ ]:





# In[ ]:





# In[ ]:




