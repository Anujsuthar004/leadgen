"""
config.py — Central configuration for Lead Gen System
Edit this file to change areas, categories, and search behaviour.
"""

AREAS = [
    # Mumbai West
    "Andheri West", "Andheri East", "Bandra West", "Bandra East",
    "Borivali West", "Borivali East", "Kandivali West", "Kandivali East",
    "Malad West", "Malad East", "Goregaon West", "Goregaon East",
    "Jogeshwari West", "Jogeshwari East", "Santacruz West", "Santacruz East",
    "Vile Parle West", "Vile Parle East",
    # Mumbai Central/East
    "Kurla", "Ghatkopar West", "Ghatkopar East", "Vikhroli",
    "Mulund West", "Mulund East", "Powai", "Chembur",
    "Dadar", "Prabhadevi", "Worli", "Lower Parel",
    "Mahalaxmi", "Grant Road", "Byculla", "Parel",
    # South Mumbai
    "Fort", "Nariman Point", "Colaba", "Churchgate",
    "Marine Lines", "Cuffe Parade",
    # Navi Mumbai
    "Vashi", "Nerul", "Belapur", "Kharghar",
    "Panvel", "Airoli", "Ghansoli", "Kopar Khairane",
    "Sanpada", "Turbhe",
    # Thane
    "Thane West", "Thane East", "Kalwa", "Mumbra",
    "Dombivli West", "Dombivli East", "Kalyan West", "Kalyan East",
    "Ulhasnagar", "Ambernath", "Badlapur",
    # Mira-Vasai Belt
    "Mira Road", "Bhayander West", "Bhayander East",
    "Vasai", "Virar West", "Virar East",
]

# Category → (search keyword for Google Maps, recommended service)
CATEGORIES = {
    "CA Firm":              ("CA firm",               "Automation"),
    "Chartered Accountant": ("chartered accountant",  "Automation"),
    "Clinic":               ("clinic",                "Automation"),
    "Doctor":               ("doctor",                "Automation"),
    "Dentist":              ("dentist",               "Automation"),
    "Physiotherapist":      ("physiotherapist",       "Automation"),
    "Hospital":             ("hospital",              "Automation"),
    "Restaurant":           ("restaurant",            "Web Dev"),
    "Cafe":                 ("cafe",                  "Web Dev"),
    "Retail Store":         ("retail store",          "Web Dev"),
    "Clothing Store":       ("clothing store",        "Web Dev"),
    "Coaching Class":       ("coaching class",        "Both"),
    "Tuition Centre":       ("tuition centre",        "Both"),
    "Salon":                ("salon",                 "Web Dev"),
    "Gym":                  ("gym",                   "Both"),
    "Pharmacy":             ("pharmacy",              "Web Dev"),
}

# Scraper behaviour
MAX_RESULTS_PER_SEARCH = 20   # per area×category combo — keep low to avoid blocks
DELAY_MIN = 2.5               # seconds between actions
DELAY_MAX = 5.0               # seconds between actions
HEADLESS = False               # False = browser visible (safer for testing)
MAX_RETRIES = 2               # retries on block/timeout

# File paths
DATA_DIR = "data"
LEADS_CSV = f"{DATA_DIR}/leads.csv"
ARCHIVE_DIR = f"{DATA_DIR}/archive"

# Legacy CSVs are migrated into data/leads.csv on first run.
LEGACY_RAW_CSV = "leads_raw.csv"
LEGACY_ENRICHED_CSV = "leads_enriched.csv"
LEGACY_EMAIL_LOG_CSV = "email_log.csv"

# Google Sheets
SHEET_NAME = "Leadgen Tracker"   # name of the tab inside your sheet

# Lead scoring weights (used by scorer.py)
SCORE_WEIGHTS = {
    "has_website":    20,   # biggest single signal for reachability
    "has_phone":      10,
    "rating_4_plus":  25,   # credible, established business
    "rating_4_5_plus": 10,  # bonus for exceptional rating
    "reviews_20_plus": 15,  # proven review volume
    "reviews_100_plus": 10, # bonus for well-known business
    "category_premium": 10, # higher service value categories
}

PREMIUM_CATEGORIES = {
    "CA Firm", "Chartered Accountant",
    "Clinic", "Dentist", "Physiotherapist", "Hospital", "Doctor",
}
