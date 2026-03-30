"""
scorer.py — Lead quality scoring (0–100).

Score breakdown:
  has_website:       20 pts  — biggest reachability signal
  has_phone:         10 pts
  rating >= 4.0:     25 pts  — credible, established business
  rating >= 4.5:     +10 pts — bonus for exceptional rating
  reviews >= 20:     15 pts  — proven review volume
  reviews >= 100:    +10 pts — bonus for well-known business
  premium category:  10 pts  — CA Firm, Clinic, Dentist, etc.

Max: 100 pts
"""

from config import SCORE_WEIGHTS, PREMIUM_CATEGORIES


def score_lead(row: dict) -> int:
    score = 0

    if row.get("Website", "").strip():
        score += SCORE_WEIGHTS["has_website"]

    if row.get("Phone", "").strip():
        score += SCORE_WEIGHTS["has_phone"]

    try:
        rating = float(row.get("Rating", "0") or "0")
        if rating >= 4.0:
            score += SCORE_WEIGHTS["rating_4_plus"]
        if rating >= 4.5:
            score += SCORE_WEIGHTS["rating_4_5_plus"]
    except (ValueError, TypeError):
        pass

    try:
        reviews = int(str(row.get("Reviews", "0") or "0").replace(",", ""))
        if reviews >= 20:
            score += SCORE_WEIGHTS["reviews_20_plus"]
        if reviews >= 100:
            score += SCORE_WEIGHTS["reviews_100_plus"]
    except (ValueError, TypeError):
        pass

    if row.get("Category", "") in PREMIUM_CATEGORIES:
        score += SCORE_WEIGHTS["category_premium"]

    return min(score, 100)


def sort_leads_by_score(rows: list[dict]) -> list[dict]:
    """Return rows sorted highest score first. Adds 'Score' key to each row."""
    for row in rows:
        row["Score"] = score_lead(row)
    return sorted(rows, key=lambda r: r["Score"], reverse=True)
