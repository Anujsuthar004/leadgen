"""
enricher.py — Visits each lead's website and tries to find a contact email.

Priority order (per page):
  1. JSON-LD schema.org markup (ContactPoint.email embedded by SEO plugins)
  2. Footer-targeted mailto: links and regex scan
  3. mailto: links anywhere on page
  4. Regex scan of full page text

Pages crawled per lead:
  1. Homepage (all strategies above)
  2. Up to 2 contact-style sub-pages (contact, reach, enquiry…)
  3. Up to 2 secondary sub-pages (about, team, staff…)

Reads from leads_raw.csv, writes to leads_enriched.csv (sorted by lead score).

Run:
  python enricher.py
"""

import csv
import json
import re
import time
import random
from pathlib import Path
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from rich.console import Console

from config import RAW_CSV, ENRICHED_CSV, DELAY_MIN, DELAY_MAX
from scorer import sort_leads_by_score

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
    """Extract all valid emails from raw HTML (mailto links + regex)."""
    soup = BeautifulSoup(html, "html.parser")
    emails = []
    seen = set()

    # Priority 1: mailto: links
    for a in soup.find_all("a", href=True):
        href = a["href"]
        if href.startswith("mailto:"):
            email = href.replace("mailto:", "").split("?")[0].strip().lower()
            if EMAIL_REGEX.match(email) and is_valid_email(email) and email not in seen:
                emails.append(email)
                seen.add(email)

    # Priority 2: regex scan of full text
    for match in EMAIL_REGEX.findall(soup.get_text()):
        m = match.lower()
        if is_valid_email(m) and m not in seen:
            emails.append(m)
            seen.add(m)

    return emails


def extract_emails_from_jsonld(html: str) -> list[str]:
    """
    Extract emails from schema.org JSON-LD script blocks.
    Many Indian SMB sites (CA firms, clinics) embed ContactPoint.email
    via Yoast/Rank Math SEO plugins — invisible to text scan but machine-readable.
    """
    emails = []
    seen = set()
    soup = BeautifulSoup(html, "html.parser")
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            flat = json.dumps(data)
            for match in EMAIL_REGEX.findall(flat):
                m = match.lower()
                if is_valid_email(m) and m not in seen:
                    emails.append(m)
                    seen.add(m)
        except (json.JSONDecodeError, TypeError):
            continue
    return emails


def extract_emails_from_footer(html: str) -> list[str]:
    """
    Target the <footer> element specifically — a common location for contact
    emails that can get diluted in a full-page regex scan.
    """
    emails = []
    seen = set()
    soup = BeautifulSoup(html, "html.parser")
    footer = soup.find("footer")
    if not footer:
        return emails

    # mailto links in footer first
    for a in footer.find_all("a", href=True):
        if a["href"].startswith("mailto:"):
            email = a["href"].replace("mailto:", "").split("?")[0].strip().lower()
            if EMAIL_REGEX.match(email) and is_valid_email(email) and email not in seen:
                emails.append(email)
                seen.add(email)

    # regex scan of footer text
    for match in EMAIL_REGEX.findall(footer.get_text()):
        m = match.lower()
        if is_valid_email(m) and m not in seen:
            emails.append(m)
            seen.add(m)

    return emails


def find_candidate_urls(base_url: str, soup: BeautifulSoup) -> list[str]:
    """
    Return up to 4 sub-page URLs likely to contain contact emails.
    Contact-style pages take priority; about/team pages are secondary.
    """
    priority_kw = ["contact", "reach", "get-in-touch", "enquiry", "inquiry"]
    secondary_kw = ["about", "team", "staff", "our-team", "people"]

    seen: set[str] = set()
    priority_urls: list[str] = []
    secondary_urls: list[str] = []

    for a in soup.find_all("a", href=True):
        href = a["href"].lower()
        full = urljoin(base_url, a["href"])
        if urlparse(full).netloc != urlparse(base_url).netloc:
            continue
        if full in seen or full == base_url:
            continue
        seen.add(full)

        if any(kw in href for kw in priority_kw):
            priority_urls.append(full)
        elif any(kw in href for kw in secondary_kw):
            secondary_urls.append(full)

    return (priority_urls[:2] + secondary_urls[:2])[:4]


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


def _try_all_strategies(html: str) -> str:
    """Run all extraction strategies on a page. Returns first email found or ''."""
    for extractor in (extract_emails_from_jsonld, extract_emails_from_footer, extract_emails_from_html):
        found = extractor(html)
        if found:
            return found[0]
    return ""


def enrich_lead(website: str) -> str:
    """
    Given a website URL, try to find a contact email.
    Returns email string or "Not Found".
    """
    if not website:
        return "Not Found"

    html, final_url = fetch_page(website)
    if not html:
        return "Not Found"

    # Try all strategies on homepage first
    email = _try_all_strategies(html)
    if email:
        return email

    # Crawl sub-pages: contact → about → team
    soup = BeautifulSoup(html, "html.parser")
    for candidate_url in find_candidate_urls(final_url, soup):
        delay()
        sub_html, _ = fetch_page(candidate_url)
        if not sub_html:
            continue
        email = _try_all_strategies(sub_html)
        if email:
            return email

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

    # Sort by lead quality — highest-score leads are enriched (and later emailed) first
    rows = sort_leads_by_score(rows)

    console.print(f"\n[bold blue]Email Enricher[/bold blue]")
    console.print(f"Processing {len(rows)} leads (sorted by score) with 10 threads...\n")

    results = [None] * len(rows)
    lock = __import__('threading').Lock()

    def process(i, row):
        name    = row.get("Business Name", "")
        website = row.get("Website", "").strip()
        email   = "No Website" if not website else enrich_lead(website)
        enriched_row = dict(row)
        enriched_row["Email"] = email
        results[i] = enriched_row
        with lock:
            status = (
                f"[green]{email[:50]}[/green]"
                if email not in ("Not Found", "No Website")
                else f"[dim]{email.lower()}[/dim]"
            )
            score = row.get("Score", "?")
            console.print(f"[dim]{i+1}/{len(rows)}[/dim] [{score:>3}] {name[:38]:<38} {status}")

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
