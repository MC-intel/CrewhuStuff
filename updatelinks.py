import csv
import json
import re
import base64
import requests
from pathlib import Path

# ==========
# CONFIG
# ==========
CSV_FILE = Path("/content/Lost Surveys(Survey History (5)).csv")
JSON_FILE = Path("crewhu_notifications_NEW.json")

DRY_RUN = True   # ← Set False to actually update ConnectWise

COMPANY_ID = "pearlsolves"
PUBLIC_KEY = "AVk7JkjVIiTjjnle"
PRIVATE_KEY = "HVy911UWKBMVGAwb"
CLIENT_ID = "43c39678-9ed1-4fd4-8ccf-db2d5a9dab10"

API_BASE = "https://api-na.myconnectwise.net/v2025_1/apis/3.0"


# ==========
# AUTH
# ==========
def build_headers():
    auth_string = f"{COMPANY_ID}+{PUBLIC_KEY}:{PRIVATE_KEY}"
    auth_base64 = base64.b64encode(auth_string.encode()).decode()
    return {
        "Authorization": f"Basic {auth_base64}",
        "clientId": CLIENT_ID,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


# ==========
# STEP 1 — LOAD CSV TICKET NUMBERS (robust)
# ==========
def load_ticket_numbers_from_csv(csv_path):
    encodings_to_try = ["utf-8-sig", "utf-16", "latin-1"]
    content = None

    # Try decoding raw CSV text
    for enc in encodings_to_try:
        try:
            raw = csv_path.read_text(encoding=enc)
            print(f"[INFO] CSV loaded using encoding: {enc}")
            content = raw.splitlines()
            break
        except Exception:
            print(f"[WARN] CSV decode failed with {enc}")

    if content is None:
        raise Exception("CSV could not be decoded with utf-8-sig, utf-16, or latin-1")

    # Show header
    header_line = content[0]
    print(f"[INFO] CSV HEADER: {header_line}")

    # Detect delimiter
    possible_delims = [',', ';', '\t', '|']
    detected_delim = next((d for d in possible_delims if d in header_line), ',')
    print(f"[INFO] CSV delimiter detected as: '{detected_delim}'")

    # Parse CSV
    reader = csv.DictReader(content, delimiter=detected_delim)
    header_fields = [h.strip().lower() for h in reader.fieldnames]
    print(f"[INFO] CSV Fields: {header_fields}")

    # Auto-detect ticket column
    candidate_keywords = ["ticket", "sr", "id", "workorder"]
    ticket_col = next((col for col in header_fields if any(k in col for k in candidate_keywords)), None)

    if not ticket_col:
        raise Exception("No ticket-like column found in CSV.")

    print(f"[INFO] Ticket column detected as: '{ticket_col}'")

    # Extract & normalize ticket numbers
    tickets = set()

    for row in reader:
        val = row.get(ticket_col)
        if not val:
            continue

        raw = val.strip()

        # Normalize by removing all non-digits
        digits = re.sub(r"\D", "", raw)

        if digits.isdigit():
            tickets.add(digits)
        else:
            print(f"[WARN] Could not normalize ticket value: '{raw}'")

    print(f"[INFO] Total ticket numbers extracted: {len(tickets)}")
    return sorted(tickets, key=int)


# ==========
# STEP 2 — LOAD JSON (handles UTF-8 BOM)
# ==========
def load_notifications_from_json(json_path):
    encodings = ["utf-8-sig", "utf-8", "latin-1"]
    for enc in encodings:
        try:
            with json_path.open("r", encoding=enc) as f:
                print(f"[INFO] Loaded JSON using encoding: {enc}")
                return json.load(f)
        except json.JSONDecodeError:
            print(f"[WARN] JSON decode failed with {enc}")
            continue

    raise Exception("JSON file could not be loaded with safe encodings.")


# ==========
# STEP 3 — EXTRACT CREWHU SURVEY LINK FROM JSON
# ==========
SURVEY_LINK_PATTERN = re.compile(
    r"https://web\.crewhu\.com/#/managesurvey/form/[^\s<>\"']+"
)

def get_survey_link_for_ticket(ticket_number, notifications):
    ticket_pattern = f"ticket# {ticket_number}"

    for notif in notifications:
        body = notif.get("FullBody", "")
        if ticket_pattern not in body:
            continue

        match = SURVEY_LINK_PATTERN.search(body)
        if match:
            return match.group(0).rstrip(">.")

    return None


# ==========
# STEP 4 — UPDATE CONNECTWISE FIELD
# ==========
def update_ticket_crewhu_field(ticket_number, survey_link, headers):
    url = f"{API_BASE}/service/tickets/{int(ticket_number)}"
    resp = requests.get(url, headers=headers)

    if resp.status_code != 200:
        print(f"[{ticket_number}] ERROR GET {resp.status_code}")
        return

    ticket = resp.json()
    fields = ticket.get("customFields", [])

    # Find Crewhu field
    candidates = [
        f for f in fields
        if "crewhu" in f.get("caption", "").lower()
        or f.get("caption", "").lower() == "latest crewhu survey"
    ]

    if not candidates:
        print(f"[{ticket_number}] No Crewhu custom field found.")
        return

    field = candidates[-1]
    idx = fields.index(field)
    current_val = (field.get("value") or "").strip()

    # Skip if already filled with a link
    if SURVEY_LINK_PATTERN.search(current_val):
        print(f"[{ticket_number}] SKIP — Field already contains link.")
        return

    # Skip if field is not empty
    if current_val not in ("", None):
        print(f"[{ticket_number}] SKIP — Field not empty: '{current_val}'")
        return

    print(f"[{ticket_number}] READY → Set field to: {survey_link}")

    # DRY RUN
    if DRY_RUN:
        print(f"[{ticket_number}] DRY RUN — No update sent.")
        return

    patch_body = [
        {"op": "replace", "path": f"/customFields/{idx}/value", "value": survey_link}
    ]

    patch_resp = requests.patch(url, headers=headers, json=patch_body)

    if patch_resp.status_code in (200, 204):
        print(f"[{ticket_number}] UPDATED.")
    else:
        print(f"[{ticket_number}] PATCH ERROR {patch_resp.status_code}: {patch_resp.text[:200]}")


# ==========
# MAIN
# ==========
def main():
    headers = build_headers()

    print("Loading CSV tickets...")
    tickets = load_ticket_numbers_from_csv(CSV_FILE)

    print("Loading JSON notifications...")
    notifications = load_notifications_from_json(JSON_FILE)

    print(f"\n*** DRY RUN = {DRY_RUN} ***\n")

    for t in tickets:
        print(f"\n=== Ticket {t} ===")
        link = get_survey_link_for_ticket(t, notifications)

        if not link:
            print(f"[{t}] No survey link found.")
            continue

        print(f"[{t}] Link found: {link}")
        update_ticket_crewhu_field(t, link, headers)


if __name__ == "__main__":
    main()
