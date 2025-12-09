# re-format json

import json
import re

# ---------------------------------------------------------
# Configuration
# ---------------------------------------------------------
INPUT_FILE = '/content/crewhu_notifications_clean.json'
OUTPUT_FILE = 'crewhu_surveys_clean.json'

def parse_crewhu_data():
    try:
        with open(INPUT_FILE, 'r', encoding='utf-8-sig') as f:
            emails = json.load(f)
    except FileNotFoundError:
        print(f"Error: Could not find {INPUT_FILE}")
        return
    except json.JSONDecodeError:
        print(f"Error: Invalid JSON format in {INPUT_FILE}")
        return

    surveys = {}

    # ---------------------------------------------------------
    # Regex Patterns
    # ---------------------------------------------------------

    # 1. Pattern for "Review" style emails
    # "Name from Company gave a Rating rating to Employee for Categories on ticket# ID (Desc)."
    regex_review = re.compile(
        r"(?P<customer>.*?) from (?P<company>.*?) gave a (?P<rating>.*?) rating to (?P<employee>.*?) for (?P<categories>.*?) on ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>.*?)\)",
        re.IGNORECASE
    )

    # 2. Pattern for "Woohoo" style emails
    # "Name from Company gave a Rating Rating for Categories on ticket# ID (Desc) to your colleague Employee."
    regex_woohoo = re.compile(
        r"(?P<customer>.*?) from (?P<company>.*?) gave a (?P<rating>.*?) Rating for (?P<categories>.*?) on ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>.*?)\) to your colleague (?P<employee>.*?)",
        re.IGNORECASE
    )

    # 3. Pattern for Feedback (looks at the whole body)
    regex_feedback = re.compile(
        r"Customer feedback:\s*(?:\"(?P<quote>.*?)\"|(?P<none>No feedback provided))",
        re.IGNORECASE | re.DOTALL
    )

    print(f"Scanning {len(emails)} emails...")

    for email in emails:
        subject = email.get('Subject', '')
        full_body = email.get('FullBody', '')

        # Skip if it's not a rating email
        if 'rating' not in subject.lower():
            continue

        match_data = None

        # We split by lines to find the specific sentence and avoid "EXTERNAL EMAIL" headers
        cleaned_lines = [line.strip() for line in full_body.splitlines() if line.strip()]

        for line in cleaned_lines:
            # Try matching the "Review" format line
            m1 = regex_review.search(line)
            if m1:
                match_data = m1.groupdict()
                break

            # Try matching the "Woohoo" format line
            m2 = regex_woohoo.search(line)
            if m2:
                match_data = m2.groupdict()
                break

        if match_data:
            # Extract Ticket ID
            ticket_id_str = match_data['ticket_id']
            ticket_id_int = int(ticket_id_str)

            # Cleanup Extracted Data
            customer = match_data['customer'].strip()
            company = match_data['company'].strip()
            rating = match_data['rating'].strip()
            employee = match_data['employee'].strip().rstrip('.') # remove trailing period
            categories = match_data['categories'].strip()
            ticket_desc = match_data['ticket_desc'].strip()

            # Extract Feedback from the full body block
            feedback_text = "No feedback provided."
            fb_match = regex_feedback.search(full_body)
            if fb_match:
                if fb_match.group('quote'):
                    feedback_text = fb_match.group('quote').strip()
                elif fb_match.group('none'):
                    feedback_text = "No feedback provided."

            # Construct the specific sentence format requested
            # "Customer from Company just gave a Positive rating to Employee for Categories on ticket# 123 (Desc)."
            summary_sentence = (
                f"{customer} from {company} just gave a {rating} rating to {employee} "
                f"for {categories} on ticket# {ticket_id_str} ({ticket_desc})."
            )

            # Add to dictionary (deduplicate by Ticket ID)
            surveys[ticket_id_int] = {
                "ticket_number": ticket_id_int,
                "summary": summary_sentence,
                "customer_feedback": feedback_text
            }

    # ---------------------------------------------------------
    # Sorting and Saving
    # ---------------------------------------------------------

    # Sort by ticket number
    sorted_data = sorted(surveys.values(), key=lambda x: x['ticket_number'])

    # Save to JSON
    try:
        with open(OUTPUT_FILE, 'w', encoding='utf-8') as f:
            json.dump(sorted_data, f, indent=4)
        print(f"Successfully processed {len(sorted_data)} unique surveys.")
        print(f"Output saved to: {OUTPUT_FILE}")
    except IOError as e:
        print(f"Error saving file: {e}")

if __name__ == "__main__":
    parse_crewhu_data()
