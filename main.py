#!/usr/bin/env python
# coding: utf-8

# In[3]:


import csv
import json
import os
from pathlib import Path
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup


RUN_MODE = os.getenv("RUN_MODE", "local").strip().lower()

BASE_URL = "https://careers.deloitte.ca/search/"

EXCLUDE_KEYWORDS = [
    "student", "first nations", "tax", "grad", "graduate", "accountant"
]

LOCAL_DATA_DIR = Path(".")
RAILWAY_DATA_DIR = Path("./data")

TELEGRAM_BOT_TOKEN = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
TELEGRAM_CHAT_ID = os.getenv("TELEGRAM_CHAT_ID", "").strip()


def get_data_dir():
    d = RAILWAY_DATA_DIR if RUN_MODE == "railway" else LOCAL_DATA_DIR
    d.mkdir(parents=True, exist_ok=True)
    return d


DATA_DIR = get_data_dir()
CSV_FILE = DATA_DIR / "deloitte_jobs.csv"
STATE_FILE = DATA_DIR / "seen_jobs.json"


def should_keep(title):
    t = title.lower()
    return not any(word in t for word in EXCLUDE_KEYWORDS)


def get_page(page):
    params = {
        "q": "",
        "locationsearch": "",
        "searchResultView": "LIST",
        "sortBy": "",
        "pageNumber": page,
    }
    url = BASE_URL + "?" + urlencode(params)

    res = requests.get(url, timeout=20)
    return res.text


def parse_jobs(html):
    soup = BeautifulSoup(html, "html.parser")
    jobs = []

    for a in soup.select("a[href*='/job/']"):
        title = a.get_text(strip=True)
        href = a.get("href")

        if not href or not title:
            continue

        if not should_keep(title):
            continue

        if href.startswith("/"):
            href = "https://careers.deloitte.ca" + href

        jobs.append({"title": title, "url": href})

    return jobs


def load_seen():
    if not STATE_FILE.exists():
        return {}
    return json.loads(STATE_FILE.read_text())


def save_seen(data):
    STATE_FILE.write_text(json.dumps(data, indent=2))


def send_telegram(msg):
    if not TELEGRAM_BOT_TOKEN or not TELEGRAM_CHAT_ID:
        return

    requests.post(
        f"https://api.telegram.org/bot{TELEGRAM_BOT_TOKEN}/sendMessage",
        data={"chat_id": TELEGRAM_CHAT_ID, "text": msg},
        timeout=20,
    )


def main():
    print("RUN_MODE:", RUN_MODE)

    seen = load_seen()
    new_jobs = []
    all_jobs = []

    for page in range(1, 5):
        html = get_page(page)
        jobs = parse_jobs(html)

        if not jobs:
            break

        for job in jobs:
            all_jobs.append(job)
            if job["url"] not in seen:
                new_jobs.append(job)
                seen[job["url"]] = job["title"]

    with open(CSV_FILE, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerow(["title", "url"])
        for j in all_jobs:
            writer.writerow([j["title"], j["url"]])

    save_seen(seen)

    print("New jobs:", len(new_jobs))

    for job in new_jobs[:10]:
        send_telegram(f"{job['title']}\n{job['url']}")


if __name__ == "__main__":
    main()


# In[ ]:





# In[2]:





# In[ ]:





# In[ ]:





# In[ ]:




