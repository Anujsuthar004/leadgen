"""
followup.py — Send follow-up emails to leads contacted 5+ days ago.

Logic:
  1. Read email_log.csv
  2. Find rows where Status="Sent" AND Sent At >= --days days ago
  3. Exclude emails that already have a "Followup Sent" row in the log
  4. Send a short 2-3 sentence follow-up (no attachments)
  5. Append new row with Status="Followup Sent" to email_log.csv

Run:
  python followup.py                 # send follow-ups due (default: 5+ days)
  python followup.py --dry-run       # preview without sending
  python followup.py --days 7        # change follow-up window
"""

import csv
import os
import smtplib
import time
import random
import argparse
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

load_dotenv()
console = Console()

LOG_CSV         = "email_log.csv"
LOG_HEADERS     = ["Email", "Business Name", "Category", "Area", "Status", "Sent At", "Error"]
SENDER_EMAIL    = os.getenv("SENDER_EMAIL", "")
SENDER_PASSWORD = os.getenv("SENDER_APP_PASSWORD", "")
DELAY_MIN       = 15
DELAY_MAX       = 25
DEFAULT_DAYS    = 5

FOLLOWUP_SUBJECT = "Re: Quick follow-up — {name}"

FOLLOWUP_PLAIN = """\
Hi,

Just following up on my previous email about WhatsApp automation for {business_name}.

I know inboxes get busy — would a 10-minute call this week work to see if this could save your team a few hours every week?

Anuj Suthar
📞 8928361781
GitHub: https://github.com/Anujsuthar004
"""

FOLLOWUP_HTML = """\
<html><body style="font-family: Arial, sans-serif; font-size: 14px; color: #222; max-width: 600px;">
<p>Hi,</p>
<p>Just following up on my previous email about <strong>WhatsApp automation</strong> for {business_name}.</p>
<p>I know inboxes get busy — would a <strong>10-minute call this week</strong> work to see if this could save your team a few hours every week?</p>
<br>
<p>
  <strong>Anuj Suthar</strong><br>
  📞 8928361781<br>
  <a href="https://github.com/Anujsuthar004">GitHub</a>
</p>
</body></html>
"""


def _parse_sent_date(sent_at: str) -> datetime | None:
    for fmt in ("%d %b %Y %H:%M", "%d %b %Y"):
        try:
            return datetime.strptime(sent_at.strip(), fmt)
        except ValueError:
            continue
    return None


def load_log() -> list[dict]:
    if not Path(LOG_CSV).exists():
        return []
    with open(LOG_CSV, "r", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def get_followup_candidates(rows: list[dict], min_days: int) -> list[dict]:
    """
    Return leads eligible for a follow-up:
    - Status == "Sent" (original email)
    - Sent At >= min_days days ago
    - No "Followup Sent" row exists for this email
    """
    cutoff = datetime.now() - timedelta(days=min_days)
    already_followed = {
        r["Email"].lower()
        for r in rows
        if r.get("Status") == "Followup Sent"
    }
    seen: set[str] = set()
    candidates = []
    for row in rows:
        if row.get("Status") != "Sent":
            continue
        email = row.get("Email", "").lower()
        if email in already_followed or email in seen:
            continue
        sent_dt = _parse_sent_date(row.get("Sent At", ""))
        if sent_dt and sent_dt <= cutoff:
            candidates.append(row)
            seen.add(email)
    return candidates


def build_followup_email(lead: dict) -> MIMEMultipart:
    business = lead.get("Business Name", "your business")
    to_email = lead.get("Email", "")
    subject  = FOLLOWUP_SUBJECT.format(name=business[:30])

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = f"Anuj Suthar <{SENDER_EMAIL}>"
    msg["To"]      = to_email
    msg["Reply-To"] = SENDER_EMAIL
    msg.attach(MIMEText(FOLLOWUP_PLAIN.format(business_name=business), "plain"))
    msg.attach(MIMEText(FOLLOWUP_HTML.format(business_name=business), "html"))
    return msg


def get_smtp():
    smtp = smtplib.SMTP_SSL("smtp.gmail.com", 465)
    smtp.login(SENDER_EMAIL, SENDER_PASSWORD)
    return smtp


def append_log(row: dict):
    write_header = not Path(LOG_CSV).exists()
    with open(LOG_CSV, "a", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=LOG_HEADERS)
        if write_header:
            writer.writeheader()
        writer.writerow(row)


def run(min_days: int = DEFAULT_DAYS, dry_run: bool = False):
    if not SENDER_PASSWORD and not dry_run:
        console.print("[red]SENDER_APP_PASSWORD not set in .env[/red]")
        return

    rows = load_log()
    if not rows:
        console.print("[yellow]email_log.csv not found or empty.[/yellow]")
        return

    candidates = get_followup_candidates(rows, min_days)

    console.print(Panel.fit(
        f"[bold blue]Follow-up Emailer[/bold blue]\n"
        f"Leads due (>= {min_days} days, no prior follow-up): {len(candidates)}  |  "
        f"{'[yellow]DRY RUN[/yellow]' if dry_run else '[green]LIVE[/green]'}",
        border_style="blue"
    ))

    if not candidates:
        console.print("[green]No follow-ups due.[/green]")
        return

    if not dry_run:
        try:
            test = get_smtp()
            test.quit()
            console.print("[green]Gmail credentials verified.[/green]\n")
        except Exception as e:
            console.print(f"[red]Gmail login failed: {e}[/red]")
            return

    sent = 0
    for i, lead in enumerate(candidates, 1):
        email = lead.get("Email", "")
        name  = lead.get("Business Name", "")
        sent_at = lead.get("Sent At", "")
        console.print(f"[dim]{i}/{len(candidates)}[/dim] {name[:40]:<40} [cyan]{email}[/cyan]  [dim](orig: {sent_at})[/dim]")

        if dry_run:
            console.print("  [yellow]DRY RUN — would send follow-up[/yellow]")
            continue

        try:
            smtp = get_smtp()
            msg  = build_followup_email(lead)
            smtp.sendmail(SENDER_EMAIL, email, msg.as_string())
            smtp.quit()
            append_log({
                "Email":         email,
                "Business Name": name,
                "Category":      lead.get("Category", ""),
                "Area":          lead.get("Area", ""),
                "Status":        "Followup Sent",
                "Sent At":       datetime.now().strftime("%d %b %Y %H:%M"),
                "Error":         "",
            })
            sent += 1
            console.print("  [green]✓ Follow-up sent[/green]")
        except Exception as e:
            console.print(f"  [red]Failed: {e}[/red]")

        if i < len(candidates):
            wait = random.randint(DELAY_MIN, DELAY_MAX)
            console.print(f"  [dim]Waiting {wait}s...[/dim]")
            time.sleep(wait)

    console.print(f"\n[bold green]Done.[/bold green] Follow-ups sent: {sent}/{len(candidates)}")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Follow-up Email Sender")
    parser.add_argument("--days", type=int, default=DEFAULT_DAYS,
                        help=f"Minimum days since initial email (default: {DEFAULT_DAYS})")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without sending")
    args = parser.parse_args()
    run(min_days=args.days, dry_run=args.dry_run)
