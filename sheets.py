"""
sheets.py — Syncs enriched leads to Google Sheets.

- Reads leads_enriched.csv
- Deduplicates by phone number
- Pushes new rows to Google Sheet
- Never overwrites existing rows (safe to re-run)

Sheet columns:
  A: Business Name
  B: Category
  C: Service
  D: Area
  E: Phone
  F: Website
  G: Email
  H: Outreach Status   ← you fill this manually
  I: Channel           ← you fill this manually
  J: Last Contact Date ← you fill this manually
  K: Follow-up Date    ← you fill this manually
  L: Notes             ← you fill this manually
  M: Scraped At

Setup:
  1. console.cloud.google.com → New project "leadgen"
  2. Enable Google Sheets API + Google Drive API
  3. Create Service Account → download JSON → save as credentials.json
  4. Share your Google Sheet with the service account email
  5. Create .env with GOOGLE_SHEET_ID and GOOGLE_CREDENTIALS_PATH

Run:
  python sheets.py
"""

import csv
import os
from pathlib import Path
from dotenv import load_dotenv

import gspread
from google.oauth2.service_account import Credentials
from rich.console import Console

from config import ENRICHED_CSV, SHEET_NAME

load_dotenv()
console = Console()

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

SHEET_HEADERS = [
    "Business Name", "Category", "Service", "Area",
    "Phone", "Website", "Email",
    "Outreach Status", "Channel",
    "Last Contact Date", "Follow-up Date", "Notes",
    "Scraped At"
]

# Map CSV columns to sheet columns
CSV_TO_SHEET = {
    "Business Name": "Business Name",
    "Category":      "Category",
    "Service":       "Service",
    "Area":          "Area",
    "Phone":         "Phone",
    "Website":       "Website",
    "Email":         "Email",
    "Scraped At":    "Scraped At",
}


def get_sheet():
    """Authenticate and return the worksheet."""
    creds_path = os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json")
    sheet_id   = os.getenv("GOOGLE_SHEET_ID", "")

    if not Path(creds_path).exists():
        console.print(f"[red]credentials.json not found at: {creds_path}[/red]")
        console.print("[yellow]Follow setup instructions in sheets.py docstring.[/yellow]")
        raise FileNotFoundError(f"Missing: {creds_path}")

    if not sheet_id:
        console.print("[red]GOOGLE_SHEET_ID not set in .env[/red]")
        raise ValueError("Missing GOOGLE_SHEET_ID")

    creds = Credentials.from_service_account_file(creds_path, scopes=SCOPES)
    client = gspread.authorize(creds)

    spreadsheet = client.open_by_key(sheet_id)

    # Get or create the named worksheet
    try:
        worksheet = spreadsheet.worksheet(SHEET_NAME)
    except gspread.WorksheetNotFound:
        worksheet = spreadsheet.add_worksheet(
            title=SHEET_NAME, rows=5000, cols=len(SHEET_HEADERS)
        )
        console.print(f"[green]Created worksheet: {SHEET_NAME}[/green]")

    return worksheet


def ensure_headers(worksheet):
    """Write headers if sheet is empty."""
    existing = worksheet.row_values(1)
    if not existing:
        worksheet.update("A1", [SHEET_HEADERS])
        console.print("[green]Headers written to sheet.[/green]")


def get_existing_phones(worksheet) -> set:
    """Return set of phone numbers already in the sheet."""
    try:
        phone_col_idx = SHEET_HEADERS.index("Phone") + 1
        phones = worksheet.col_values(phone_col_idx)
        return set(p.strip() for p in phones if p.strip())
    except Exception:
        return set()


def csv_row_to_sheet_row(row: dict) -> list:
    """Convert a CSV dict row to a list matching SHEET_HEADERS order."""
    result = []
    for header in SHEET_HEADERS:
        if header in CSV_TO_SHEET.values():
            # Find matching CSV key
            csv_key = next(
                (k for k, v in CSV_TO_SHEET.items() if v == header), None
            )
            result.append(row.get(csv_key, "") if csv_key else "")
        else:
            result.append("")  # manual columns left blank
    return result


def run_sync():
    if not Path(ENRICHED_CSV).exists():
        console.print(f"[red]{ENRICHED_CSV} not found. Run enricher.py first.[/red]")
        return

    with open(ENRICHED_CSV, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        rows = list(reader)

    if not rows:
        console.print("[yellow]No leads to sync.[/yellow]")
        return

    console.print(f"\n[bold blue]Google Sheets Sync[/bold blue]")
    console.print(f"Leads to process: {len(rows)}\n")

    try:
        worksheet = get_sheet()
        ensure_headers(worksheet)
        existing_phones = get_existing_phones(worksheet)
        console.print(f"Existing rows in sheet: {len(existing_phones)}")

        new_rows = []
        skipped = 0

        for row in rows:
            phone = row.get("Phone", "").strip()
            # Skip if phone already in sheet (or if no phone and name already there)
            if phone and phone in existing_phones:
                skipped += 1
                continue
            new_rows.append(csv_row_to_sheet_row(row))

        if not new_rows:
            console.print("[yellow]No new leads to add. Sheet is up to date.[/yellow]")
            return

        # Batch append
        worksheet.append_rows(new_rows, value_input_option="USER_ENTERED")

        console.print(f"[bold green]✓ Added {len(new_rows)} new leads[/bold green]")
        console.print(f"[dim]Skipped {skipped} duplicates[/dim]")
        console.print(f"\nOpen your sheet: "
                      f"[cyan]https://docs.google.com/spreadsheets/d/{os.getenv('GOOGLE_SHEET_ID')}[/cyan]")

    except FileNotFoundError:
        pass  # already printed error
    except Exception as e:
        console.print(f"[red]Sheets error: {e}[/red]")
        raise


if __name__ == "__main__":
    run_sync()
