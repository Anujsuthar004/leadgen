# 🗺️ Lead Gen System

> Scrapes local businesses from Google Maps → enriches with emails via website crawl → syncs everything to Google Sheets for outreach tracking.

Built for scraping Mumbai/MMR businesses (clinics, CA firms, restaurants, etc.) across 50+ areas, but fully configurable for any city or category.

---

## What it does

1. **Scrapes Google Maps** — searches `"{category} near {area}"`, collects business name, phone, website, address, rating
2. **Enriches with email** — visits each business website and extracts contact emails
3. **Syncs to Google Sheets** — pushes to a pre-structured tracker sheet with columns for manual outreach notes

---

## Tech Stack

| Layer | Tool |
|---|---|
| Scraping | [Playwright](https://playwright.dev/python/) (headless Chromium) |
| Email extraction | `requests` + `BeautifulSoup` |
| Google Sheets API | `gspread` + `google-auth` |
| Config | Python + `.env` |
| Output | CSV + Google Sheets |

---

## Project Structure

```
leadgen/
├── main.py              # Entry point + CLI flags
├── scraper.py           # Google Maps scraper (Playwright)
├── enricher.py          # Email extraction from business websites
├── sheets.py            # Google Sheets sync
├── config.py            # Areas, categories, scraper behaviour
├── requirements.txt     # Python dependencies
├── .env.example         # Template for environment variables
└── credentials.json.example  # Template for Google service account
```

---

## Setup

### 1. Install dependencies

```bash
pip install -r requirements.txt
playwright install chromium
```

### 2. Configure environment

Copy the example files and fill in your values:

```bash
cp .env.example .env
cp credentials.json.example credentials.json
```

`.env`:
```
GOOGLE_SHEET_ID=your_google_sheet_id_here
GOOGLE_CREDENTIALS_PATH=credentials.json
```

### 3. Set up Google Sheets API

1. Go to [console.cloud.google.com](https://console.cloud.google.com) → **New Project**
2. Enable **Google Sheets API** and **Google Drive API**
3. Go to **Credentials** → **Create Credentials** → **Service Account**
4. Name it anything (e.g. `leadgen-bot`) → Create
5. Open the service account → **Keys** tab → **Add Key** → JSON
6. Download the JSON → rename it `credentials.json` → put it in the project folder
7. Open your Google Sheet → **Share** → paste the `client_email` from `credentials.json` → Editor access
8. Copy the Sheet ID from the URL: `docs.google.com/spreadsheets/d/THIS_PART/edit`
9. Paste it in `.env` as `GOOGLE_SHEET_ID`

---

## Running

### Quick test (one area, one category, no sheets)

```bash
python main.py --areas "Andheri West" --categories "CA Firm" --no-sheets
```

Check `leads_raw.csv` — if it looks good, proceed.

### Full pipeline

```bash
python main.py
```

### Other options

```bash
# Specific areas and categories
python main.py --areas "Bandra West" "Andheri East" --categories "Clinic" "CA Firm"

# Scrape only (skip email enrichment and sheets)
python main.py --scrape-only

# Enrich + sync only (skip scraping, use existing leads_raw.csv)
python main.py --skip-scrape
```

---

## Output

| File | Contents |
|---|---|
| `leads_raw.csv` | Name, phone, website, address, rating |
| `leads_enriched.csv` | Same + email column |
| Google Sheet | Full tracker with outreach status columns |

### Google Sheet columns

| Column | Source |
|---|---|
| Business Name, Category, Area, Phone, Website, Email, Scraped At | Auto-filled by scraper |
| Service (Web Dev / Automation) | Based on category in `config.py` |
| Outreach Status, Channel, Last Contact, Follow-up Date, Notes | You fill these manually |

---

## Configuration

Edit `config.py` to change:

- **`AREAS`** — list of areas to search
- **`CATEGORIES`** — business types + recommended service mapping
- **`MAX_RESULTS_PER_SEARCH`** — results per area×category (keep low to avoid blocks)
- **`DELAY_MIN` / `DELAY_MAX`** — seconds between actions
- **`HEADLESS`** — `False` = visible browser (safer for testing)

---

## Tips

- Start with `HEADLESS = False` so you can see what's happening
- Test 1-2 areas before running all of MMR
- If Google blocks you, increase delays or wait 30 min
- Both CSV and Sheets sync are **idempotent** — safe to re-run, won't duplicate

---

## Troubleshooting

**"No results panel found"** — Google Maps changed its layout. Check selectors in `scraper.py`.

**Rate limited / CAPTCHA** — Increase `DELAY_MIN`/`DELAY_MAX`. Run non-headless. Wait and retry.

**Email not found** — Normal. Most small businesses don't list email publicly. Use phone/WhatsApp.

**Sheets auth error** — Confirm you shared the sheet with the service account email in `credentials.json`.

---

## ⚠️ Usage Note

This tool is for personal outreach/research only. Respect Google's Terms of Service and local data privacy regulations. Do not run at aggressive speeds.
