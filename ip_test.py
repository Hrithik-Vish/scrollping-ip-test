"""
ScrollPing — GitHub Actions IP viability test harness.

Purpose: NOT part of the real scraper. This is throwaway research code to
answer one question — do these sites block requests coming from a
GitHub-hosted runner IP, and if so, is it immediate or does it degrade
over repeated hourly requests?

Runs once per invocation (GitHub Actions calls this once per scheduled
run, once per hour). Appends one CSV row per site to results.csv, which
the workflow commits back to the repo after each run so the full history
accumulates over the 1-3 day test window.

Columns:
    timestamp_utc   - ISO8601 UTC timestamp of this run
    site_name       - short label for the site
    url             - the URL fetched
    status_code     - HTTP status code, or "EXCEPTION" if the request
                       itself failed (timeout/connection error)
    error_detail    - exception class name / message if status_code is
                       EXCEPTION, else blank
    response_length - len(response.text), 0 if no response
    looks_blocked   - heuristic bool: response came back but is
                       suspiciously short or contains common
                       anti-bot/challenge markers (see LOOKS_BLOCKED_MARKERS)
    found_links     - count of <a> tags matching the chapter-link pattern,
                       reusing the same regex as parsing.py. This is the
                       real signal: status 200 with 0 found_links usually
                       means you got a challenge page or a changed layout,
                       not a working page.
"""

import csv
import os
import re
import time
from datetime import datetime, timezone

import requests
from bs4 import BeautifulSoup

RESULTS_FILE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "results.csv")

CSV_HEADERS = [
    "timestamp_utc",
    "site_name",
    "url",
    "status_code",
    "error_detail",
    "response_length",
    "looks_blocked",
    "found_links",
]

# Sites to test, in priority order. site_name is just a label for the CSV.
SITES = [
    {"site_name": "asurascans", "url": "https://asurascans.com/", "priority": "core"},
    {"site_name": "hivetoons", "url": "https://hivetoons.org/", "priority": "core"},
    {"site_name": "kunmanga", "url": "https://www.kunmanga.online/", "priority": "core"},
    {"site_name": "mgeko", "url": "https://www.mgeko.cc/", "priority": "secondary"},
    {"site_name": "mangadex", "url": "https://mangadex.org/", "priority": "secondary"},
    {"site_name": "vortexscans", "url": "https://vortexscans.org/", "priority": "secondary"},
]

USER_AGENT_HEADER = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/150.0.0.0 Safari/537.36"
    )
}

# Same chapter-link regex as parsing.py, kept in sync manually since this
# is standalone test code, not an import of the real package.
CHAPTER_LINK_PATTERN = re.compile(
    r"[/-]?(chapters?|chs?|episodes?|eps?|titles?)[/-]?(\d+(\.\d+)?)"
)

# Rough textual markers that show up on common bot-challenge / block pages.
# This is a heuristic, not proof — always eyeball found_links and
# response_length too, don't trust this bool alone.
LOOKS_BLOCKED_MARKERS = [
    "checking your browser",
    "just a moment",
    "cf-browser-verification",
    "attention required",
    "access denied",
    "captcha",
    "cloudflare",
    "ddos protection by",
    "enable javascript and cookies",
    "unusual traffic",
]

# Minimum response length below which a "successful" (200) response is
# still suspicious — real category/homepage HTML is normally tens of KB.
MIN_PLAUSIBLE_LENGTH = 2000


def fetch_html(url):
    """
    Same shape as the real fetching.py, but returns a dict of diagnostics
    instead of just the HTML text, since this harness needs to know status
    codes and exception detail, not just pass/fail.
    """
    try:
        response = requests.get(url, timeout=(5, 30), headers=USER_AGENT_HEADER)
        # Keep response.text regardless of status code — a 403/503 block
        # page's body is exactly what looks_blocked() and found_links need
        # to inspect. Discarding it on non-200 would hide the block reason.
        return {
            "status_code": response.status_code,
            "error_detail": "",
            "text": response.text or "",
            "response_length": len(response.text) if response.text else 0,
        }
    except requests.exceptions.ConnectTimeout as e:
        return {"status_code": "EXCEPTION", "error_detail": f"ConnectTimeout: {e}", "text": "", "response_length": 0}
    except requests.exceptions.ConnectionError as e:
        return {"status_code": "EXCEPTION", "error_detail": f"ConnectionError: {e}", "text": "", "response_length": 0}
    except requests.exceptions.RequestException as e:
        return {"status_code": "EXCEPTION", "error_detail": f"RequestException: {e}", "text": "", "response_length": 0}


def looks_blocked(text, response_length):
    if not text:
        return False  # no body to judge; status_code/EXCEPTION already tells the story
    lowered = text.lower()
    if any(marker in lowered for marker in LOOKS_BLOCKED_MARKERS):
        return True
    if response_length < MIN_PLAUSIBLE_LENGTH:
        return True
    return False


def count_chapter_links(text):
    if not text:
        return 0
    try:
        soup = BeautifulSoup(text, "lxml")
    except Exception:
        return 0
    return len(soup.find_all("a", href=CHAPTER_LINK_PATTERN))


def ensure_csv_header():
    file_exists = os.path.isfile(RESULTS_FILE)
    if not file_exists:
        with open(RESULTS_FILE, "w", newline="", encoding="utf-8") as f:
            writer = csv.writer(f)
            writer.writerow(CSV_HEADERS)


def run():
    ensure_csv_header()
    timestamp = datetime.now(timezone.utc).isoformat()

    rows = []
    for site in SITES:
        result = fetch_html(site["url"])
        blocked_guess = looks_blocked(result["text"], result["response_length"])
        link_count = count_chapter_links(result["text"])

        row = [
            timestamp,
            site["site_name"],
            site["url"],
            result["status_code"],
            result["error_detail"],
            result["response_length"],
            blocked_guess,
            link_count,
        ]
        rows.append(row)

        print(
            f"[{site['priority']:<9}] {site['site_name']:<12} "
            f"status={result['status_code']} len={result['response_length']} "
            f"looks_blocked={blocked_guess} links_found={link_count}"
        )

        # Small stagger between requests so this run doesn't look like a
        # single burst of near-simultaneous hits across 6 different sites.
        time.sleep(2)

    with open(RESULTS_FILE, "a", newline="", encoding="utf-8") as f:
        writer = csv.writer(f)
        writer.writerows(rows)

    print(f"\nAppended {len(rows)} rows to {RESULTS_FILE}")


if __name__ == "__main__":
    run()
