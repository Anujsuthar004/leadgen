"""
followup.py — Send follow-up emails to leads contacted 5+ days ago.

Logic:
  1. Read data/leads.csv
  2. Find rows where Outreach Status="Contacted" AND Last Contact Date >= --days days ago
  3. Exclude leads that already have a Follow-up Date
  4. Send a short 2-3 sentence follow-up (no attachments)
  5. Update the same leads.csv row with follow-up details

Run:
  python followup.py                 # send follow-ups due (default: 5+ days)
  python followup.py --dry-run       # preview without sending
  python followup.py --days 7        # change follow-up window
"""

import os
import smtplib
import time
import random
import argparse
from datetime import datetime, timedelta
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText

from dotenv import load_dotenv
from rich.console import Console
from rich.panel import Panel

from config import LEADS_CSV
from leads_store import load_leads, now_timestamp, save_leads

load_dotenv()
console = Console()

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
    for fmt in ("%Y-%m-%d %H:%M", "%d %b %Y %H:%M", "%d %b %Y"):
        try:
            return datetime.strptime(sent_at.strip(), fmt)
        except ValueError:
            continue
    return None


def get_followup_candidates(rows: list[dict], min_days: int) -> list[dict]:
    """
    Return leads eligible for a follow-up:
    - Outreach Status == "Contacted" (original email sent)
    - Last Contact Date >= min_days days ago
    - No Follow-up Date exists yet
    """
    cutoff = datetime.now() - timedelta(days=min_days)
    candidates = []
    for row in rows:
        if row.get("Outreach Status") != "Contacted":
            continue
        if row.get("Follow-up Date", "").strip():
            continue
        sent_dt = _parse_sent_date(row.get("Last Contact Date", ""))
        if sent_dt and sent_dt <= cutoff:
            candidates.append(row)
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

def run(min_days: int = DEFAULT_DAYS, dry_run: bool = False):
    if not SENDER_PASSWORD and not dry_run:
        console.print("[red]SENDER_APP_PASSWORD not set in .env[/red]")
        return

    rows = load_leads()
    if not rows:
        console.print(f"[yellow]{LEADS_CSV} not found or empty.[/yellow]")
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
        sent_at = lead.get("Last Contact Date", "")
        console.print(f"[dim]{i}/{len(candidates)}[/dim] {name[:40]:<40} [cyan]{email}[/cyan]  [dim](orig: {sent_at})[/dim]")

        if dry_run:
            console.print("  [yellow]DRY RUN — would send follow-up[/yellow]")
            continue

        try:
            smtp = get_smtp()
            msg  = build_followup_email(lead)
            smtp.sendmail(SENDER_EMAIL, email, msg.as_string())
            smtp.quit()
            followup_time = now_timestamp()
            lead["Outreach Status"] = "Followed Up"
            lead["Channel"] = "Email"
            lead["Last Contact Date"] = followup_time
            lead["Follow-up Date"] = followup_time
            lead["Updated At"] = followup_time
            save_leads(rows)
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
