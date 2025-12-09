import json
import base64
import os
import requests
from datetime import datetime, timezone
from pathlib import Path

# ==============================
# CONFIG – DRY RUN
# ==============================
DRY_RUN = True   # Set to False to actually post notes

# ==============================
# CONFIG – FILES
# ==============================
def detect_base_dir() -> Path:
    env_dir = os.environ.get("CREWHU_DATA_DIR")
    if env_dir:
        return Path(env_dir).expanduser().resolve()

    try:
        return Path(__file__).parent.resolve()
    except NameError:
        # __file__ is not defined in some interactive environments (e.g., Colab)
        return Path.cwd()


BASE_DIR = detect_base_dir()
PARSED_JSON = Path(os.environ.get("CREWHU_SURVEY_FILE", BASE_DIR / "crewhu_surveys_clean.json"))

# ==============================
# CONFIG – CONNECTWISE CREDS
# ==============================
COMPANY_ID = "pearlsolves"
PUBLIC_KEY = "fBnI5wBwwDk0Cquk"
PRIVATE_KEY = "kQDyrfqPqhoo4tGY"
CLIENT_ID = "43c39678-9ed1-4fd4-8ccf-db2d5a9dab10"

API_BASE = "https://na.myconnectwise.net/v4_6_release/apis/3.0"


# ==============================
# AUTH
# ==============================
def get_headers():
    auth_string = f"{COMPANY_ID}+{PUBLIC_KEY}:{PRIVATE_KEY}"
    auth_base64 = base64.b64encode(auth_string.encode()).decode()
    return {
        "Authorization": f"Basic {auth_base64}",
        "clientId": CLIENT_ID,
        "Accept": "application/json",
        "Content-Type": "application/json"
    }


# ==============================
# DELETE OLD AUTOMATED NOTES
# ==============================
def delete_automated_notes(ticket_id, headers):
    # This function finds ANY note (Internal or Discussion) with the specific
    # automated text and deletes it to prevent duplicates.
    if DRY_RUN:
        print(f"[{ticket_id}] (DRY RUN) Would delete old automation notes.")
        return

    notes_url = f"{API_BASE}/service/tickets/{ticket_id}/notes"

    try:
        resp = requests.get(notes_url, headers=headers)
        if resp.status_code != 200:
            print(f"[{ticket_id}] ❌ Failed to fetch notes: {resp.status_code}")
            return

        notes = resp.json()
        deleted = 0

        for note in notes:
            note_id = note.get("id")
            text = (note.get("text") or "")

            # Delete notes created by our script to prevent duplicates
            if "just gave a" in text and "Customer feedback:" in text:
                del_url = f"{notes_url}/{note_id}"
                d = requests.delete(del_url, headers=headers)
                if d.status_code in (200, 204):
                    print(f"[{ticket_id}] 🗑️ Deleted old auto note {note_id}")
                    deleted += 1

        if deleted == 0:
            print(f"[{ticket_id}] No old automation notes found.")

    except Exception as e:
        print(f"[{ticket_id}] ❌ Error during deletion: {e}")


# ==============================
# POST NEW NOTE (INTERNAL)
# ==============================
def post_note(ticket_id, summary, feedback, headers):
    url = f"{API_BASE}/service/tickets/{ticket_id}/notes"

    # Construct the final note text
    final_note_text = f"{summary}\n\nCustomer feedback:\n{feedback}"

    if DRY_RUN:
        print(f"\n[{ticket_id}] === DRY RUN NOTE (INTERNAL) ===")
        print(final_note_text)
        print("===============================\n")
        return

    # FLAGS UPDATED HERE FOR INTERNAL TAB
    payload = {
        "text": final_note_text,
        "detailDescriptionFlag": False, # False = Do not put in Discussion
        "internalAnalysisFlag": True,   # True = Put in Internal Analysis
        "resolutionFlag": False,        # False = Do not put in Resolution
        "createdBy": "Crewhu API",
        "dateCreated": datetime.now(timezone.utc).isoformat()
    }

    try:
        response = requests.post(url, headers=headers, json=payload)

        if response.status_code == 201:
            print(f"[{ticket_id}] ✅ Posted updated INTERNAL note")
        else:
            print(f"[{ticket_id}] ❌ Error posting note: {response.status_code} {response.text[:200]}")
    except Exception as e:
        print(f"[{ticket_id}] ❌ Connection Error: {e}")


# ==============================
# MAIN LOGIC
# ==============================
def main():
    headers = get_headers()

    if not PARSED_JSON.exists():
        print(f"ERROR: {PARSED_JSON} not found. Please run the parser script first.")
        return

    with PARSED_JSON.open("r", encoding="utf-8") as f:
        parsed_data = json.load(f)

    print(f"Loaded {len(parsed_data)} parsed Crewhu entries.")

    for entry in parsed_data:
        # 1. Extract data from new JSON format
        ticket_id = entry.get("ticket_number")
        summary = entry.get("summary", "").strip()
        feedback = entry.get("customer_feedback", "No feedback provided.").strip()

        if not ticket_id:
            print("Skipping entry with missing ticket number.")
            continue

        print(f"\n=== Processing ticket {ticket_id} ===")

        # 2. Delete old automated notes (safety check - removes duplicates even if they were in Discussion tab)
        delete_automated_notes(ticket_id, headers)

        # 3. Post the new note (Internal Tab)
        post_note(ticket_id, summary, feedback, headers)

    if DRY_RUN:
        print("\nDRY RUN COMPLETE — no notes were posted or deleted.")
        print("Set DRY_RUN = False in the script to execute changes.")
    else:
        print("\nAll notes updated successfully.")

if __name__ == "__main__":
    main()
