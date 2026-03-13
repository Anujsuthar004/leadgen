"""
scraper.py — Scrapes Google Maps for business leads.

For each (area, category) pair:
  - Opens Google Maps
  - Searches "{keyword} in {area} Mumbai"
  - Scrolls through results
  - Extracts: name, phone, website, address, rating, category, service
  - Saves to leads_raw.csv (appends, never overwrites)

Run directly:
  python scraper.py --areas "Andheri West" --categories "CA Firm" "Clinic"
  python scraper.py  # runs all areas × all categories (long)
"""

import csv
import os
import random
import time
import argparse
from datetime import datetime
from pathlib import Path

from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from rich.console import Console
from rich.progress import track
from rich import print as rprint

from config import (
    AREAS, CATEGORIES, MAX_RESULTS_PER_SEARCH,
    DELAY_MIN, DELAY_MAX, HEADLESS, MAX_RETRIES, RAW_CSV
)

console = Console()

CSV_HEADERS = [
    "Business Name", "Category", "Service", "Area",
    "Phone", "Website", "Address", "Rating", "Reviews",
    "Scraped At"
]


def delay(min_s=None, max_s=None):
    """Random delay to mimic human behaviour."""
    time.sleep(random.uniform(
        min_s or DELAY_MIN,
        max_s or DELAY_MAX
    ))


def init_csv():
    """Create CSV with headers if it doesn't exist."""
    if not Path(RAW_CSV).exists():
        with open(RAW_CSV, "w", newline="", encoding="utf-8") as f:
            writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
            writer.writeheader()
        console.print(f"[green]Created {RAW_CSV}[/green]")


def load_existing_keys():
    """
    Load (name, area) pairs already scraped.
    Used to skip duplicates on re-runs.
    """
    keys = set()
    if not Path(RAW_CSV).exists():
        return keys
    with open(RAW_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            keys.add((row["Business Name"].strip().lower(), row["Area"].strip().lower()))
    return keys


def append_rows(rows: list[dict]):
    """Append a list of lead dicts to the CSV."""
    if not rows:
        return
    with open(RAW_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_HEADERS)
        writer.writerows(rows)


def extract_listing_detail(page) -> dict:
    """
    After clicking a listing, extract all details from the side panel.
    Returns a dict with phone, website, address, rating, reviews.
    """
    result = {
        "Phone": "",
        "Website": "",
        "Address": "",
        "Rating": "",
        "Reviews": "",
    }

    try:
        # Wait for panel to load
        page.wait_for_selector('role=main', timeout=5000)
        delay(1, 2)

        # Rating
        try:
            rating_el = page.query_selector('div.F7nice span[aria-hidden="true"]')
            if rating_el:
                result["Rating"] = rating_el.inner_text().strip()
        except Exception:
            pass

        # Reviews count
        try:
            reviews_el = page.query_selector('div.F7nice span[aria-label*="review"]')
            if reviews_el:
                result["Reviews"] = reviews_el.get_attribute("aria-label").split()[0]
        except Exception:
            pass

        # Address, Phone, Website — these share a similar button structure
        info_buttons = page.query_selector_all('button[data-item-id]')
        for btn in info_buttons:
            item_id = btn.get_attribute("data-item-id") or ""
            text = btn.inner_text().strip()

            if item_id.startswith("address") and not result["Address"]:
                result["Address"] = text.replace("\n", ", ")

            elif item_id.startswith("phone:tel:") and not result["Phone"]:
                result["Phone"] = text.replace("\n", "").strip()

        # Website — look for the website link button
        try:
            web_btn = page.query_selector('a[data-item-id="authority"]')
            if web_btn:
                result["Website"] = web_btn.get_attribute("href") or ""
        except Exception:
            pass

        # Fallback phone via aria-label
        if not result["Phone"]:
            try:
                phone_el = page.query_selector('[data-tooltip="Copy phone number"]')
                if phone_el:
                    result["Phone"] = phone_el.get_attribute("aria-label", "").replace("Phone:", "").strip()
            except Exception:
                pass

    except PlaywrightTimeout:
        pass

    return result


def scrape_area_category(page, area: str, cat_name: str, keyword: str, service: str, existing_keys: set) -> list[dict]:
    """
    Searches Google Maps for '{keyword} in {area} Mumbai'.
    Scrolls and extracts up to MAX_RESULTS_PER_SEARCH listings.
    Returns list of lead dicts.
    """
    query = f"{keyword} in {area} Mumbai"
    url = f"https://www.google.com/maps/search/{query.replace(' ', '+')}"
    leads = []

    for attempt in range(MAX_RETRIES + 1):
        try:
            console.print(f"  [cyan]→ {query}[/cyan]")
            page.goto(url, wait_until="domcontentloaded", timeout=30000)
            delay(3, 5)

            # Dismiss consent popup if present
            try:
                agree_btn = page.query_selector('button[aria-label*="Accept"]')
                if agree_btn:
                    agree_btn.click()
                    delay(1, 2)
            except Exception:
                pass

            # Find results panel
            results_panel = page.query_selector('div[role="feed"]')
            if not results_panel:
                console.print(f"  [yellow]No results panel found for: {query}[/yellow]")
                return leads

            # Scroll to load more results
            scroll_count = 0
            max_scrolls = MAX_RESULTS_PER_SEARCH // 5
            while scroll_count < max_scrolls:
                page.evaluate('document.querySelector(\'div[role="feed"]\').scrollBy(0, 800)')
                delay(1.5, 3)
                scroll_count += 1

                # Check if end of results
                end_el = page.query_selector('span.HlvSq')
                if end_el:
                    break

            # Fast approach: collect hrefs first, then open each in a new tab.
            # The search results page stays loaded — no re-navigation needed.
            raw_listings = page.query_selector_all('div[role="feed"] > div > div > a')
            listing_data = []  # list of (name, href)
            for el in raw_listings:
                try:
                    n = el.get_attribute("aria-label") or ""
                    h = el.get_attribute("href") or ""
                    n = n.strip()
                    if n and h:
                        listing_data.append((n, h))
                except Exception:
                    continue
            console.print(f"  [dim]Found {len(listing_data)} listings[/dim]")

            context = page.context
            count = 0

            for name, href in listing_data:
                if count >= MAX_RESULTS_PER_SEARCH:
                    break

                key = (name.lower(), area.lower())
                if key in existing_keys:
                    continue

                try:
                    # Open listing in new tab — search results page stays intact
                    detail_page = context.new_page()
                    detail_page.goto(href, wait_until="domcontentloaded", timeout=20000)
                    delay(1.5, 2.5)

                    detail = extract_listing_detail(detail_page)
                    detail_page.close()

                    lead = {
                        "Business Name": name,
                        "Category": cat_name,
                        "Service": service,
                        "Area": area,
                        "Phone": detail["Phone"],
                        "Website": detail["Website"],
                        "Address": detail["Address"],
                        "Rating": detail["Rating"],
                        "Reviews": detail["Reviews"],
                        "Scraped At": datetime.now().strftime("%Y-%m-%d %H:%M"),
                    }

                    leads.append(lead)
                    existing_keys.add(key)
                    count += 1

                    console.print(
                        f"  [green]✓[/green] {name[:45]:<45} "
                        f"[dim]{detail['Phone'] or 'no phone'}[/dim]"
                    )
                    delay(1, 2)

                except Exception as e:
                    console.print(f"  [yellow]Skipped '{name[:35]}': {str(e)[:50]}[/yellow]")
                    try:
                        detail_page.close()
                    except Exception:
                        pass
                    delay(1, 2)
                    continue

            return leads

        except PlaywrightTimeout as e:
            console.print(f"  [red]Timeout on attempt {attempt+1}: {e}[/red]")
            if attempt < MAX_RETRIES:
                console.print("  [yellow]Retrying in 30s...[/yellow]")
                time.sleep(30)
            else:
                console.print("  [red]Max retries reached. Skipping.[/red]")
                return leads

        except Exception as e:
            console.print(f"  [red]Unexpected error: {e}[/red]")
            return leads

    return leads


def run_scraper(areas: list[str], categories: dict):
    """Main scraper loop. Iterates areas × categories."""
    init_csv()
    existing_keys = load_existing_keys()
    total_scraped = 0

    console.print(f"\n[bold blue]Lead Gen Scraper[/bold blue]")
    console.print(f"Areas: {len(areas)}  |  Categories: {len(categories)}  |  "
                  f"Max per search: {MAX_RESULTS_PER_SEARCH}\n")

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=HEADLESS,
            args=[
                "--no-sandbox",
                "--disable-blink-features=AutomationControlled",
            ]
        )

        context = browser.new_context(
            viewport={
                "width": random.randint(1200, 1440),
                "height": random.randint(800, 900)
            },
            user_agent=(
                "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                "AppleWebKit/537.36 (KHTML, like Gecko) "
                "Chrome/120.0.0.0 Safari/537.36"
            ),
            locale="en-IN",
            timezone_id="Asia/Kolkata",
        )

        page = context.new_page()

        # Mask automation signals
        page.add_init_script("""
            Object.defineProperty(navigator, 'webdriver', { get: () => undefined });
            Object.defineProperty(navigator, 'plugins', { get: () => [1, 2, 3] });
        """)

        try:
            for area in areas:
                console.rule(f"[bold]{area}[/bold]")
                for cat_name, (keyword, service) in categories.items():
                    leads = scrape_area_category(
                        page, area, cat_name, keyword, service, existing_keys
                    )
                    if leads:
                        append_rows(leads)
                        total_scraped += len(leads)
                        console.print(
                            f"  [bold green]Saved {len(leads)} leads "
                            f"(total: {total_scraped})[/bold green]\n"
                        )
                    delay(DELAY_MIN, DELAY_MAX)

        except KeyboardInterrupt:
            console.print("\n[yellow]Interrupted. Progress saved to CSV.[/yellow]")

        finally:
            context.close()
            browser.close()

    console.print(f"\n[bold green]Done. Total leads scraped: {total_scraped}[/bold green]")
    console.print(f"Saved to: [cyan]{RAW_CSV}[/cyan]")


# ── CLI ──────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Google Maps Lead Scraper")
    parser.add_argument(
        "--areas", nargs="+",
        help="Specific areas to scrape (default: all from config)",
        default=None
    )
    parser.add_argument(
        "--categories", nargs="+",
        help="Specific category names to scrape (default: all from config)",
        default=None
    )
    args = parser.parse_args()

    selected_areas = args.areas if args.areas else AREAS
    selected_cats = (
        {k: v for k, v in CATEGORIES.items() if k in args.categories}
        if args.categories else CATEGORIES
    )

    if args.categories and not selected_cats:
        console.print(f"[red]No matching categories. Available: {list(CATEGORIES.keys())}[/red]")
        exit(1)

    run_scraper(selected_areas, selected_cats)
