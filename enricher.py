"""
enricher.py — Visits each lead's website and tries to find a contact email.

Priority order:
  1. mailto: links on homepage
  2. mailto: links on /contact page
  3. Regex scan of page text for email patterns
  4. Marks "Not Found" if nothing found

Reads from leads_raw.csv, writes to leads_enriched.csv.

Run:
  python enricher.py
"""

import csv
import re
import time
import random
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rich.console import Console

from config import RAW_CSV, ENRICHED_CSV, DELAY_MIN, DELAY_MAX

console = Console()

EMAIL_REGEX = re.compile(
    r"[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,}"
)

# Emails to ignore — generic noise
IGNORE_PATTERNS = [
    "example.com", "yourdomain", "domain.com",
    "email.com", "sentry.io", "wix.com",
    "wordpress.com", "placeholder", "test@",
    "noreply", "no-reply", "support@wix",
]

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-IN,en;q=0.9",
}


def delay():
    time.sleep(random.uniform(DELAY_MIN, DELAY_MAX))


def is_valid_email(email: str) -> bool:
    """Filter out obviously fake/template emails."""
    email_lower = email.lower()
    return not any(pattern in email_lower for pattern in IGNORE_PATTERNS)


def extract_emails_from_html(html: str) -> list[str]:
    """Extract all valid emails from raw HTML."""
    soup = BeautifulSoup(html, "html.parser")

    emails = set()

    # Priority 1: mailto: links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip()
            if EMAIL_REGEX.match(email) and is_valid_email(email):
                emails.add(email)

    # Priority 2: regex scan of full text
    text = soup.get_text()
    for match in EMAIL_REGEX.findall(text):
        if is_valid_email(match):
            emails.add(match)

    return list(emails)


def find_contact_url(base_url: str, soup: BeautifulSoup) -> str | None:
    """Look for a /contact or /contact-us link on the page."""
    contact_keywords = ["contact", "reach", "get-in-touch", "enquiry", "inquiry"]
    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        if any(kw in href for kw in contact_keywords):
            full = urljoin(base_url, a["href"])
            # Stay on same domain
            if urlparse(full).netloc == urlparse(base_url).netloc:
                return full
    return None


def fetch_page(url: str, timeout: int = 10) -> tuple[str, str]:
    """
    Fetch a URL. Returns (html, final_url).
    Returns ("", "") on failure.
    """
    try:
        if not url.startswith("http"):
            url = "https://" + url
        resp = requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)
        resp.raise_for_status()
        return resp.text, resp.url
    except Exception:
        return "", ""


def enrich_lead(website: str) -> str:
    """
    Given a website URL, try to find a contact email.
    Returns email string or "Not Found".
    """
    if not website:
        return "Not Found"

    # Fetch homepage
    html, final_url = fetch_page(website)
    if not html:
        return "Not Found"

    emails = extract_emails_from_html(html)
    if emails:
        return emails[0]  # return first found

    # Try contact page
    soup = BeautifulSoup(html, "html.parser")
    contact_url = find_contact_url(final_url, soup)
    if contact_url:
        delay()
        contact_html, _ = fetch_page(contact_url)
        if contact_html:
            contact_emails = extract_emails_from_html(contact_html)
            if contact_emails:
                return contact_emails[0]

    return "Not Found"


def run_enricher():
    if not Path(RAW_CSV).exists():
        console.print(f"[red]{RAW_CSV} not found. Run scraper.py first.[/red]")
        return

    with open(RAW_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        console.print("[yellow]No leads to enrich.[/yellow]")
        return

    console.print(f"\n[bold blue]Email Enricher[/bold blue]")
    console.print(f"Processing {len(rows)} leads with 10 threads...\n")

    results = [None] * len(rows)
    found_count = 0
    lock = __import__('threading').Lock()

    def process(i, row):
        name    = row.get("Business Name", "")
        website = row.get("Website", "").strip()
        if not website:
            email = "No Website"
        else:
            email = enrich_lead(website)
        enriched_row = dict(row)
        enriched_row["Email"] = email
        results[i] = enriched_row
        with lock:
            status = f"[green]{email[:50]}[/green]" if email not in ("Not Found","No Website") else f"[dim]{email.lower()}[/dim]"
            console.print(f"[dim]{i+1}/{len(rows)}[/dim] {name[:40]:<40} {status}")

    from concurrent.futures import ThreadPoolExecutor
    with ThreadPoolExecutor(max_workers=10) as ex:
        for i, row in enumerate(rows):
            ex.submit(process, i, row)

    enriched = [r for r in results if r is not None]
    found_count = sum(1 for r in enriched if r.get("Email") not in ("Not Found", "No Website", ""))

    fieldnames = list(dict.fromkeys(list(rows[0].keys()) + ["Email"]))
    with open(ENRICHED_CSV, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(enriched)

    console.print(f"\n[bold green]Done.[/bold green] Emails found: {found_count}/{len(rows)}")
    console.print(f"Saved to: [cyan]{ENRICHED_CSV}[/cyan]")


if __name__ == "__main__":
    run_enricher()
