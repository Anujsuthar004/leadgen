"""
emailer.py — Cold email automation for leads

Reads leads_enriched.csv → sends personalised emails via Gmail SMTP
→ logs status to Google Sheet + email_log.csv

Limits: 50 emails/day by default (safe for Gmail)
Safe to re-run — skips leads already marked "Emailed" in the log

Setup:
  1. Enable Gmail 2FA → generate App Password (not your real password)
     https://myaccount.google.com/apppasswords
  2. Add to .env:
     SENDER_EMAIL=sutharanuj530@gmail.com
     SENDER_APP_PASSWORD=xxxx xxxx xxxx xxxx

Run:
  python emailer.py                        # send to all leads with emails
  python emailer.py --category "CA Firm"  # specific category only
  python emailer.py --limit 20            # send max 20 today
  python emailer.py --dry-run             # preview without sending
"""

import csv
import os
import smtplib
import time
import argparse
import random
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.mime.base import MIMEBase
from email import encoders
from pathlib import Path
from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()

# ── Config ────────────────────────────────────────────────────────────────────

SENDER_EMAIL    = os.getenv("SENDER_EMAIL", "voolaweb@gmail.com")
SENDER_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")
ENRICHED_CSV    = "leads_enriched.csv"
LOG_CSV         = "email_log.csv"
DAILY_LIMIT     = 50
DELAY_MIN       = 15   # seconds between emails
DELAY_MAX       = 25

# Attachments — put your 3 demo screenshots in the same folder
# Name them exactly as below, or leave empty list to send without attachments
ATTACHMENTS = [
    "demo_1_bot_conversation.png",
    "demo_2_ca_alert.png",
    "demo_3_google_sheet.png",
]

# ── Email templates ───────────────────────────────────────────────────────────

SUBJECT_TEMPLATES = {
    "CA Firm":   "WhatsApp automation for {name} — quick demo",
    "Clinic":    "Automate patient intake for {name} — quick demo",
    "Dentist":   "Automate patient intake for {name} — quick demo",
    "default":   "Web automation demo for {name}",
}

# Plain text version (shown if HTML not supported)
PLAIN_TEMPLATES = {
    "CA Firm": """Hi,

I'm Anuj — I build automation systems for CA firms in Mumbai.

I built a WhatsApp bot that handles your client intake automatically:
- Client messages your WhatsApp number
- Bot collects their name, PAN, service needed, documents
- You get an instant alert with all their details
- Everything logs to a spreadsheet automatically

No more manually chasing clients for basic info. Setup takes 2-3 days.

I've attached 3 screenshots showing how it works.

Would this be useful for {business_name}? Happy to set up a quick call this week.

Anuj Suthar
Frontend Developer & Automation Engineer
📞 8928361781
GitHub: https://github.com/Anujsuthar004
""",

    "Clinic": """Hi,

I'm Anuj — I build automation systems for clinics in Mumbai.

I built a WhatsApp bot that handles patient intake automatically:
- Patient messages your WhatsApp number
- Bot collects their name, concern, preferred time
- You get an instant alert with all their details
- Everything logs to a spreadsheet automatically

No more missed inquiries or manual follow-ups. Setup takes 2-3 days.

I've attached 3 screenshots showing how it works.

Would this be useful for {business_name}? Happy to set up a quick call this week.

Anuj Suthar
Frontend Developer & Automation Engineer
📞 8928361781
GitHub: https://github.com/Anujsuthar004
""",

    "default": """Hi,

I'm Anuj — I build web and automation systems for businesses in Mumbai.

I recently built a WhatsApp automation system that handles client intake, follow-ups, and data logging automatically — saving hours of manual work every week.

I've attached 3 screenshots showing how it works.

Would this be useful for {business_name}? Happy to connect this week.

Anuj Suthar
Frontend Developer & Automation Engineer
📞 8928361781
GitHub: https://github.com/Anujsuthar004
""",
}

HTML_TEMPLATE = """
<html><body style="font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 600px;">
<p>Hi,</p>

<p>I'm <strong>Anuj</strong> — I build automation systems for {category_plural} in Mumbai.</p>

<p>I built a <strong>WhatsApp bot</strong> that handles client intake automatically:</p>
<ul>
  <li>Client messages your WhatsApp number</li>
  <li>Bot collects all their details step by step</li>
  <li>You get an <strong>instant alert</strong> with a full summary</li>
  <li>Everything logs to a spreadsheet automatically</li>
</ul>

<p>{pain_point}</p>

<p>I've attached 3 screenshots showing the full flow. Setup takes <strong>2–3 days</strong>.</p>

<p>Would this be useful for <strong>{business_name}</strong>? Happy to set up a quick call this week.</p>

<br>
<p>
  <strong>Anuj Suthar</strong><br>
  Frontend Developer &amp; Automation Engineer<br>
  📞 8928361781<br>
  <a href="https://github.com/Anujsuthar004">GitHub</a>
</p>
</body></html>
"""

PAIN_POINTS = {
    "CA Firm":   "No more chasing clients for PAN numbers, Form 16, or GST details on personal WhatsApp.",
    "Clinic":    "No more missed patient inquiries or manual appointment logging.",
    "Dentist":   "No more missed patient inquiries or manual appointment logging.",
    "default":   "No more manual follow-ups or data entry.",
}

CATEGORY_PLURAL = {
    "CA Firm":   "CA firms",
    "Clinic":    "clinics",
    "Dentist":   "dental clinics",
    "Restaurant":"restaurants",
    "Gym":       "gyms",
    "default":   "businesses",
}

# ── Log helpers ───────────────────────────────────────────────────────────────

LOG_HEADERS = ["Email", "Business Name", "Category", "Area", "Status", "Sent At", "Error"]

def load_email_log() -> set:
    """Return set of emails already contacted."""
    sent = set()
    if not Path(LOG_CSV).exists():
        return sent
    with open(LOG_CSV, "r", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if row.get("Status") == "Sent":
                sent.add(row.get("Email", "").lower())
    return sent

def append_log(row: dict):
    write_header = not Path(LOG_CSV).exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)

def update_sheet_status(email: str, status: str):
    """Mark lead as Emailed in Google Sheet."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials
        SCOPES = ["https://www.googleapis.com/auth/spreadsheets", "https://www.googleapis.com/auth/drive"]
        creds = Credentials.from_service_account_file(
            os.getenv("GOOGLE_CREDENTIALS_PATH", "credentials.json"), scopes=SCOPES
        )
        client = gspread.authorize(creds)
        sheet = client.open_by_key(os.getenv("GOOGLE_SHEET_ID"))
        ws = sheet.worksheet("Leadgen Tracker")
        # Find the row with this email
        all_emails = ws.col_values(7)  # Email column
        for i, cell_email in enumerate(all_emails, 1):
            if cell_email.lower() == email.lower():
                ws.update_cell(i, 8, status)   # Outreach Status column
                ws.update_cell(i, 9, "Email")  # Channel column
                ws.update_cell(i, 10, datetime.now().strftime("%d %b %Y"))  # Last Contact Date
                break
    except Exception as e:
        console.print(f"  [dim]Sheet update skipped: {e}[/dim]")

# ── Email sender ──────────────────────────────────────────────────────────────

def build_email(lead: dict) -> MIMEMultipart:
    category = lead.get("Category", "default")
    business = lead.get("Business Name", "your business")
    to_email  = lead.get("Email", "")

    subject_tpl = SUBJECT_TEMPLATES.get(category, SUBJECT_TEMPLATES["default"])
    subject = subject_tpl.format(name=business[:30])

    plain_tpl = PLAIN_TEMPLATES.get(category, PLAIN_TEMPLATES["default"])
    plain_body = plain_tpl.format(business_name=business)

    html_body = HTML_TEMPLATE.format(
        category_plural=CATEGORY_PLURAL.get(category, CATEGORY_PLURAL["default"]),
        pain_point=PAIN_POINTS.get(category, PAIN_POINTS["default"]),
        business_name=business,
    )

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Anuj | Voola <{SENDER_EMAIL}>"
    msg["To"]      = to_email
    msg["Reply-To"] = SENDER_EMAIL

    msg.attach(MIMEText(plain_body, "plain"))
    msg.attach(MIMEText(html_body, "html"))

    # Attach screenshots if they exist
    for filepath in ATTACHMENTS:
        if Path(filepath).exists():
            with open(filepath, "rb") as f:
                part = MIMEBase("application", "octet-stream")
                part.set_payload(f.read())
            encoders.encode_base64(part)
            part.add_header("Content-Disposition", f'attachment; filename="{Path(filepath).name}"')
            msg.attach(part)

    return msg

def send_email(smtp, msg: MIMEMultipart, to_email: str) -> bool:
    try:
        smtp.sendmail(SENDER_EMAIL, to_email, msg.as_string())
        return True
    except Exception as e:
        console.print(f"  [red]Send failed: {e}[/red]")
        return False

# ── Main ──────────────────────────────────────────────────────────────────────

def run(category_filter=None, limit=DAILY_LIMIT, dry_run=False):
    if not SENDER_PASSWORD and not dry_run:
        console.print("[red]SENDER_APP_PASSWORD not set in .env[/red]")
        console.print("Get one at: https://myaccount.google.com/apppasswords")
        return

    if not Path(ENRICHED_CSV).exists():
        console.print(f"[red]{ENRICHED_CSV} not found.[/red]")
        return

    with open(ENRICHED_CSV, "r", encoding="utf-8") as f:
        all_leads = list(csv.DictReader(f))

    already_sent = load_email_log()

    def clean_email(raw: str) -> str:
        """
        Extract the first clean valid email from a potentially messy string.
        Uses TLD whitelist to reject malformed domains like .comcac, .comcacppandey
        """
        import re
        VALID_TLDS = {
            "com","in","co","org","net","io","gov","edu","info","biz",
            "me","app","dev","ai","uk","us","au","ca","de","fr","sg",
            "nz","za","pk","bd","lk","np","ae","sa","qa","kw","bh",
        }
        JUNK_WORDS = ["services","about","today","contact","home","menu","gallery","fees","reviews","booking"]

        matches = re.findall(r'[a-zA-Z0-9._%+\-]+@[a-zA-Z0-9.\-]+\.[a-zA-Z]{2,10}', raw)
        for candidate in matches:
            email = candidate.strip().lower()
            local, domain = email.split("@")[0], email.split("@")[-1]
            if len(local) > 40:
                continue
            tld = domain.split(".")[-1]
            if tld not in VALID_TLDS:
                continue
            if any(w in local for w in JUNK_WORDS):
                continue
            return email
        return ""

    # Filter: has clean email, not already sent
    candidates = []
    skipped_bad = 0
    for r in all_leads:
        raw_email = r.get("Email", "")
        if raw_email in ("Not Found", "No Website", ""):
            continue
        clean = clean_email(raw_email)
        if not clean:
            skipped_bad += 1
            continue
        if clean in already_sent:
            continue
        if category_filter and r.get("Category") != category_filter:
            continue
        r["Email"] = clean  # replace with cleaned version
        candidates.append(r)

    if skipped_bad:
        console.print(f"[yellow]Skipped {skipped_bad} leads with invalid/malformed emails[/yellow]")

    console.print(Panel.fit(
        f"[bold blue]Email Outreach[/bold blue]\n"
        f"Candidates: {len(candidates)}  |  Limit: {limit}/day  |  "
        f"{'[yellow]DRY RUN[/yellow]' if dry_run else '[green]LIVE[/green]'}",
        border_style="blue"
    ))

    if not candidates:
        console.print("[yellow]No new leads to email.[/yellow]")
        return

    to_send = candidates[:limit]
    sent_count = 0
    failed_count = 0

    smtp = None
    if not dry_run:
        try:
            smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465)
            smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
            console.print(f"[green]Gmail connected.[/green]\n")
        except Exception as e:
            console.print(f"[red]Gmail login failed: {e}[/red]")
            console.print("Make sure you're using an App Password, not your real Gmail password.")
            return

    for i, lead in enumerate(to_send, 1):
        name     = lead.get("Business Name", "")
        email    = lead.get("Email", "")
        category = lead.get("Category", "")
        area     = lead.get("Area", "")

        console.print(f"[dim]{i}/{len(to_send)}[/dim] {name[:40]:<40} [cyan]{email}[/cyan]")

        if dry_run:
            console.print(f"  [yellow]DRY RUN — would send to {email}[/yellow]")
            continue

        msg = build_email(lead)
        success = send_email(smtp, msg, email)

        log_row = {
            "Email":         email,
            "Business Name": name,
            "Category":      category,
            "Area":          area,
            "Status":        "Sent" if success else "Failed",
            "Sent At":       datetime.now().strftime("%d %b %Y %H:%M"),
            "Error":         "" if success else "Send failed",
        }
        append_log(log_row)

        if success:
            sent_count += 1
            console.print(f"  [green]✓ Sent[/green]")
            update_sheet_status(email, "Contacted")
        else:
            failed_count += 1

        # Delay between sends — important for deliverability
        if i < len(to_send):
            wait = random.randint(DELAY_MIN, DELAY_MAX)
            console.print(f"  [dim]Waiting {wait}s...[/dim]")
            time.sleep(wait)

    if smtp:
        smtp.quit()

    console.print(f"\n[bold green]Done.[/bold green] Sent: {sent_count}  |  Failed: {failed_count}")
    console.print(f"Log saved to: [cyan]{LOG_CSV}[/cyan]")
    if sent_count > 0:
        console.print(f"[dim]Run again tomorrow for the next batch (limit: {DAILY_LIMIT}/day)[/dim]")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Cold Email Outreach")
    parser.add_argument("--category", default=None, help="Filter by category e.g. 'CA Firm'")
    parser.add_argument("--limit", type=int, default=DAILY_LIMIT, help="Max emails to send today")
    parser.add_argument("--dry-run", action="store_true", help="Preview without sending")
    args = parser.parse_args()

    run(
        category_filter=args.category,
        limit=args.limit,
        dry_run=args.dry_run
    )