"""
main.py — Runs the full lead gen pipeline.

Steps:
  1. Scrape Google Maps → leads_raw.csv
  2. Enrich with emails → leads_enriched.csv
  3. Sync to Google Sheets

Usage:
  python main.py                                    # full run, all areas + categories
  python main.py --areas "Andheri West" "Bandra"   # specific areas
  python main.py --categories "CA Firm" "Clinic"   # specific categories
  python main.py --skip-scrape                      # enrich + sync only
  python main.py --skip-enrich                      # scrape + sync only
  python main.py --scrape-only                      # scrape only, no enrich/sync
  python main.py --no-sheets                        # scrape + enrich, skip sheets sync
"""

import argparse
from rich.console import Console
from rich.panel import Panel

from config import AREAS, CATEGORIES
from scraper import run_scraper
from enricher import run_enricher
from sheets import run_sync

console = Console()


def main():
    parser = argparse.ArgumentParser(description="Lead Gen Pipeline")
    parser.add_argument("--areas", nargs="+", default=None,
                        help="Areas to scrape (default: all)")
    parser.add_argument("--categories", nargs="+", default=None,
                        help="Category names to scrape (default: all)")
    parser.add_argument("--skip-scrape", action="store_true",
                        help="Skip scraping, use existing leads_raw.csv")
    parser.add_argument("--skip-enrich", action="store_true",
                        help="Skip email enrichment")
    parser.add_argument("--scrape-only", action="store_true",
                        help="Only scrape, do not enrich or sync")
    parser.add_argument("--no-sheets", action="store_true",
                        help="Do not sync to Google Sheets")
    args = parser.parse_args()

    console.print(Panel.fit(
        "[bold blue]Lead Gen System[/bold blue]\n"
        "Google Maps → Email Enrichment → Google Sheets",
        border_style="blue"
    ))

    # Resolve areas and categories
    selected_areas = args.areas if args.areas else AREAS
    selected_cats = (
        {k: v for k, v in CATEGORIES.items() if k in args.categories}
        if args.categories else CATEGORIES
    )

    # ── Step 1: Scrape ────────────────────────────────────────────
    if not args.skip_scrape:
        console.print("\n[bold]Step 1/3 — Scraping Google Maps[/bold]")
        run_scraper(selected_areas, selected_cats)
    else:
        console.print("\n[yellow]Step 1/3 — Scraping skipped[/yellow]")

    if args.scrape_only:
        console.print("\n[green]Scrape-only mode. Done.[/green]")
        return

    # ── Step 2: Enrich ────────────────────────────────────────────
    if not args.skip_enrich:
        console.print("\n[bold]Step 2/3 — Enriching with emails[/bold]")
        run_enricher()
    else:
        console.print("\n[yellow]Step 2/3 — Enrichment skipped[/yellow]")

    # ── Step 3: Sheets ────────────────────────────────────────────
    if not args.no_sheets:
        console.print("\n[bold]Step 3/3 — Syncing to Google Sheets[/bold]")
        run_sync()
    else:
        console.print("\n[yellow]Step 3/3 — Sheets sync skipped[/yellow]")

    console.print("\n[bold green]Pipeline complete.[/bold green]")


if __name__ == "__main__":
    main()
