# Re-format CrewHu notification data

from __future__ import annotations

import argparse
import json
import os
import re
from dataclasses import dataclass
from pathlib import Path
from typing import List, Optional


# ---------------------------------------------------------
# Data classes
# ---------------------------------------------------------
@dataclass
class SurveyEntry:
    ticket_number: int
    summary: str
    customer_feedback: str

    def to_dict(self) -> dict:
        return {
            "ticket_number": self.ticket_number,
            "summary": self.summary,
            "customer_feedback": self.customer_feedback,
        }


# ---------------------------------------------------------
# Regex Patterns
# ---------------------------------------------------------
RATING_PATTERNS: List[re.Pattern[str]] = [
    # "Name from Company gave a Positive rating to Tech for Categories on ticket# 123 (Description)."
    re.compile(
        r"(?P<customer>.+?) from (?P<company>.+?) gave a (?P<rating>.+?) rating to (?P<employee>.+?) "
        r"for (?P<categories>.+?) on ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>[^)]*?)\)",
        re.IGNORECASE,
    ),
    # "Name from Company gave a Positive Rating for Categories on ticket# 123 (Description) to your colleague Tech."
    re.compile(
        r"(?P<customer>.+?) from (?P<company>.+?) gave a (?P<rating>.+?) rating for (?P<categories>.+?) "
        r"on ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>[^)]*?)\)\s*to (?:your colleague )?(?P<employee>.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
    # "Company gave a Positive rating to Tech for Categories on ticket# 123 (Description)."
    re.compile(
        r"(?P<company>.+?) gave a (?P<rating>.+?) rating to (?P<employee>.+?) for (?P<categories>.+?) "
        r"on ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>[^)]*?)\)",
        re.IGNORECASE,
    ),
    # "Name from Company gave a Positive rating to Tech for ticket# 123 (Description)." (no categories)
    re.compile(
        r"(?P<customer>.+?) from (?P<company>.+?) gave a (?P<rating>.+?) rating to (?P<employee>.+?) "
        r"for ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>[^)]*?)\)",
        re.IGNORECASE,
    ),
    # "Company gave a Positive rating to Tech for ticket# 123 (Description)." (no categories)
    re.compile(
        r"(?P<company>.+?) gave a (?P<rating>.+?) rating to (?P<employee>.+?) for ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>[^)]*?)\)",
        re.IGNORECASE,
    ),
    # "Company gave a Positive Rating for ticket# 123 (Description) to Tech." (no categories and colleague phrasing)
    re.compile(
        r"(?P<company>.+?) gave a (?P<rating>.+?) rating for ticket# (?P<ticket_id>\d+)\s*\((?P<ticket_desc>[^)]*?)\)\s*"
        r"to (?:your colleague )?(?P<employee>.+?)(?:\.|$)",
        re.IGNORECASE,
    ),
]


FEEDBACK_PATTERN = re.compile(r"Customer feedback:\s*(.*)", re.IGNORECASE | re.DOTALL)
TICKET_ID_PATTERN = re.compile(r"ticket#\s*(\d+)", re.IGNORECASE)


# ---------------------------------------------------------
# Helpers
# ---------------------------------------------------------
def detect_base_dir() -> Path:
    env_dir = os.environ.get("CREWHU_DATA_DIR")
    return Path(env_dir).expanduser().resolve() if env_dir else Path(__file__).parent.resolve()


def coalesce(*values: Optional[str], default: str = "") -> str:
    for val in values:
        if val is None:
            continue
        text = str(val).strip()
        if text:
            return text
    return default


def normalize_text(value: str) -> str:
    text = value.strip()
    return re.sub(r"\s+", " ", text)


def extract_feedback(full_body: str) -> str:
    match = FEEDBACK_PATTERN.search(full_body)
    if not match:
        return "No feedback provided."

    feedback = match.group(1).strip()
    feedback = feedback.strip('"')

    # Stop at the first blank line after the feedback body
    feedback = feedback.split("\n\n", 1)[0]
    feedback = re.split(r"\bClick here\b|Regards,", feedback, 1)[0]
    feedback = feedback.replace("\r", "\n").splitlines()
    feedback = " ".join(line.strip() for line in feedback if line.strip())

    return feedback or "No feedback provided."


def match_rating_line(full_body: str) -> Optional[dict]:
    cleaned_lines = [line.strip() for line in full_body.splitlines() if "rating" in line.lower()]

    for line in cleaned_lines:
        for pattern in RATING_PATTERNS:
            match = pattern.search(line)
            if match:
                data = match.groupdict()
                # If customer is missing, try to split "Name from Company" later
                return {k: normalize_text(v) if isinstance(v, str) else v for k, v in data.items()}
    return None


def build_summary(match_data: dict) -> Optional[SurveyEntry]:
    ticket_number = match_data.get("ticket_id") or match_data.get("ticket_number")
    if not ticket_number:
        return None

    ticket_number = int(ticket_number)

    employee = coalesce(match_data.get("employee"), default="Unknown technician")
    company = coalesce(match_data.get("company"), default="Unknown company")
    customer = coalesce(match_data.get("customer"), default="A customer")
    rating = coalesce(match_data.get("rating"), default="Positive")
    categories = coalesce(match_data.get("categories"), default="(categories not provided)")
    ticket_desc = coalesce(match_data.get("ticket_desc"), default="")

    summary_sentence = (
        f"{customer} from {company} just gave a {rating} rating to {employee} "
        f"for {categories} on ticket# {ticket_number} ({ticket_desc})."
    )

    return SurveyEntry(
        ticket_number=ticket_number,
        summary=summary_sentence,
        customer_feedback="",  # placeholder, filled later
    )


def parse_crewhu_data(input_file: Path, output_file: Path) -> List[SurveyEntry]:
    with input_file.open("r", encoding="utf-8-sig") as f:
        emails = json.load(f)

    print(f"Scanning {len(emails)} emails from {input_file} ...")

    surveys: dict[int, SurveyEntry] = {}
    missed: list[int] = []

    for email in emails:
        subject = email.get("Subject", "")
        full_body = email.get("FullBody", "")

        if "rating" not in subject.lower():
            continue

        match_data = match_rating_line(full_body)

        if not match_data:
            raw_ticket = TICKET_ID_PATTERN.search(full_body)
            if raw_ticket:
                ticket_num = int(raw_ticket.group(1))
                if ticket_num not in surveys:
                    missed.append(ticket_num)
            continue

        survey_entry = build_summary(match_data)
        if not survey_entry:
            continue

        survey_entry.customer_feedback = extract_feedback(full_body)
        surveys[survey_entry.ticket_number] = survey_entry

    sorted_entries = sorted(surveys.values(), key=lambda x: x.ticket_number)

    with output_file.open("w", encoding="utf-8") as f:
        json.dump([entry.to_dict() for entry in sorted_entries], f, indent=4)

    print(f"Successfully processed {len(sorted_entries)} unique surveys.")
    print(f"Output saved to: {output_file}")

    if missed:
        print("\nThe following tickets mentioned ratings but did not fully match a pattern:")
        for t in sorted(set(missed)):
            print(f"  - {t}")

    return sorted_entries


def parse_args() -> argparse.Namespace:
    base_dir = detect_base_dir()
    parser = argparse.ArgumentParser(description="Parse CrewHu notification emails into survey summaries.")
    parser.add_argument(
        "--input",
        type=Path,
        default=base_dir / "crewhu_notifications_clean.json",
        help="Path to the cleaned CrewHu notification JSON file.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        default=base_dir / "crewhu_surveys_clean.json",
        help="Where to write the parsed survey summaries.",
    )
    return parser.parse_args()


def main() -> None:
    args = parse_args()
    parse_crewhu_data(args.input, args.output)


if __name__ == "__main__":
    main()
