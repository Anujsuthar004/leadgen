"""
leads_store.py — Shared storage helpers for the canonical leads CSV.

The pipeline now uses a single active file at data/leads.csv.
Legacy CSVs are migrated into this file on first run and then archived.
"""

from __future__ import annotations

import csv
import re
import shutil
from datetime import datetime
from pathlib import Path
from urllib.parse import urlparse

from config import (
    ARCHIVE_DIR,
    LEADS_CSV,
    LEGACY_EMAIL_LOG_CSV,
    LEGACY_ENRICHED_CSV,
    LEGACY_RAW_CSV,
)

TIMESTAMP_FORMAT = "%Y-%m-%d %H:%M"

LEADS_HEADERS = [
    "Business Name",
    "Category",
    "Service",
    "Area",
    "Phone",
    "Website",
    "Address",
    "Rating",
    "Reviews",
    "Email",
    "Score",
    "Outreach Status",
    "Channel",
    "Last Contact Date",
    "Follow-up Date",
    "Notes",
    "Scraped At",
    "Updated At",
]


def now_timestamp() -> str:
    return datetime.now().strftime(TIMESTAMP_FORMAT)


def _ensure_storage_dirs():
    Path(LEADS_CSV).parent.mkdir(parents=True, exist_ok=True)
    Path(ARCHIVE_DIR).mkdir(parents=True, exist_ok=True)


def _read_csv_rows(path: str | Path) -> list[dict]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    with csv_path.open("r", encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def _normalize_text(value: str) -> str:
    return " ".join((value or "").strip().lower().split())


def _normalize_phone(value: str) -> str:
    return re.sub(r"\D+", "", value or "")


def _normalize_website(value: str) -> str:
    website = (value or "").strip()
    if not website:
        return ""
    if "://" not in website:
        website = f"https://{website}"
    parsed = urlparse(website)
    host = (parsed.netloc or parsed.path).lower().strip()
    return host.removeprefix("www.")


def lead_key(row: dict) -> str:
    phone = _normalize_phone(row.get("Phone", ""))
    if phone:
        return f"phone::{phone}"

    name = _normalize_text(row.get("Business Name", ""))
    area = _normalize_text(row.get("Area", ""))
    if name or area:
        return f"name-area::{name}::{area}"

    website = _normalize_website(row.get("Website", ""))
    return f"website::{website}"


def normalize_lead_row(row: dict) -> dict:
    normalized = {header: "" for header in LEADS_HEADERS}
    for header in LEADS_HEADERS:
        value = row.get(header, "")
        normalized[header] = "" if value is None else str(value).strip()

    if not normalized["Updated At"]:
        normalized["Updated At"] = normalized["Scraped At"] or now_timestamp()

    return normalized


def merge_lead_rows(existing: dict, incoming: dict) -> dict:
    merged = normalize_lead_row(existing)
    candidate = normalize_lead_row(incoming)
    changed = False

    for header in LEADS_HEADERS:
        if header == "Updated At":
            continue
        new_value = candidate.get(header, "")
        if new_value and new_value != merged.get(header, ""):
            merged[header] = new_value
            changed = True

    if changed or not merged["Updated At"]:
        merged["Updated At"] = candidate["Updated At"] or now_timestamp()

    return merged


def _sorted_rows(rows: list[dict]) -> list[dict]:
    return sorted(
        (normalize_lead_row(row) for row in rows),
        key=lambda row: (
            _normalize_text(row.get("Category", "")),
            _normalize_text(row.get("Area", "")),
            _normalize_text(row.get("Business Name", "")),
        ),
    )


def save_leads(rows: list[dict]) -> None:
    _ensure_storage_dirs()
    with Path(LEADS_CSV).open("w", encoding="utf-8", newline="") as handle:
        writer = csv.DictWriter(handle, fieldnames=LEADS_HEADERS)
        writer.writeheader()
        writer.writerows(_sorted_rows(rows))


def _merge_rows(base_rows: list[dict], incoming_rows: list[dict]) -> list[dict]:
    merged = [normalize_lead_row(row) for row in base_rows]
    key_to_index = {lead_key(row): idx for idx, row in enumerate(merged)}

    for raw_row in incoming_rows:
        candidate = normalize_lead_row(raw_row)
        key = lead_key(candidate)
        existing_idx = key_to_index.get(key)

        if existing_idx is None:
            key_to_index[key] = len(merged)
            merged.append(candidate)
            continue

        merged[existing_idx] = merge_lead_rows(merged[existing_idx], candidate)

    return merged


def _apply_legacy_email_log(rows: list[dict], log_rows: list[dict]) -> list[dict]:
    enriched = [normalize_lead_row(row) for row in rows]
    key_to_index = {lead_key(row): idx for idx, row in enumerate(enriched)}
    email_to_index = {
        row["Email"].lower(): idx
        for idx, row in enumerate(enriched)
        if row.get("Email", "").strip()
    }

    for log_row in log_rows:
        email = (log_row.get("Email") or "").strip().lower()
        if not email:
            continue

        idx = email_to_index.get(email)
        if idx is None:
            fallback_key = lead_key(
                {
                    "Business Name": log_row.get("Business Name", ""),
                    "Area": log_row.get("Area", ""),
                    "Phone": "",
                    "Website": "",
                }
            )
            idx = key_to_index.get(fallback_key)

        if idx is None:
            continue

        lead = enriched[idx]
        status = (log_row.get("Status") or "").strip()
        sent_at = (log_row.get("Sent At") or "").strip()

        lead["Email"] = lead["Email"] or email
        lead["Channel"] = lead["Channel"] or "Email"

        if status == "Sent":
            if lead["Outreach Status"] != "Followed Up":
                lead["Outreach Status"] = "Contacted"
            if sent_at and not lead["Last Contact Date"]:
                lead["Last Contact Date"] = sent_at
        elif status == "Followup Sent":
            lead["Outreach Status"] = "Followed Up"
            if sent_at:
                lead["Last Contact Date"] = sent_at
                lead["Follow-up Date"] = sent_at
        elif status == "Failed" and not lead["Outreach Status"]:
            lead["Outreach Status"] = "Email Failed"
            if sent_at and not lead["Last Contact Date"]:
                lead["Last Contact Date"] = sent_at

        lead["Updated At"] = now_timestamp()
        enriched[idx] = lead

    return enriched


def _archive_file(path: str | Path) -> None:
    file_path = Path(path)
    if not file_path.exists():
        return

    _ensure_storage_dirs()
    archived_path = Path(ARCHIVE_DIR) / file_path.name
    counter = 1
    while archived_path.exists():
        archived_path = Path(ARCHIVE_DIR) / f"{file_path.stem}_{counter}{file_path.suffix}"
        counter += 1

    shutil.move(str(file_path), archived_path)


def ensure_leads_file() -> None:
    canonical_path = Path(LEADS_CSV)
    if canonical_path.exists():
        return

    _ensure_storage_dirs()

    rows: list[dict] = []
    legacy_sources = [LEGACY_RAW_CSV, LEGACY_ENRICHED_CSV]
    for source in legacy_sources:
        rows = _merge_rows(rows, _read_csv_rows(source))

    if rows:
        rows = _apply_legacy_email_log(rows, _read_csv_rows(LEGACY_EMAIL_LOG_CSV))
        save_leads(rows)

        for source in [*legacy_sources, LEGACY_EMAIL_LOG_CSV]:
            _archive_file(source)
        return

    save_leads([])
    for source in [*legacy_sources, LEGACY_EMAIL_LOG_CSV]:
        _archive_file(source)


def load_leads() -> list[dict]:
    ensure_leads_file()
    return _read_csv_rows(LEADS_CSV)


def upsert_leads(rows: list[dict]) -> tuple[int, int]:
    existing = load_leads()
    merged = [normalize_lead_row(row) for row in existing]
    key_to_index = {lead_key(row): idx for idx, row in enumerate(merged)}
    inserted = 0
    updated = 0

    for row in rows:
        candidate = normalize_lead_row(row)
        key = lead_key(candidate)
        idx = key_to_index.get(key)

        if idx is None:
            key_to_index[key] = len(merged)
            merged.append(candidate)
            inserted += 1
            continue

        current = normalize_lead_row(merged[idx])
        merged_row = merge_lead_rows(current, candidate)
        if merged_row != current:
            updated += 1
        merged[idx] = merged_row

    save_leads(merged)
    return inserted, updated
