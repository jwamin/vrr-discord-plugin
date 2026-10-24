"""
Daily check: for each Jotform submission with a 'Date Adopted', post a Discord
reminder (tagging the vet-records person) exactly 7 and 14 days after that date.
Includes the Notes field (which has the cat's name) in the message.

Config comes from environment variables (set as GitHub Actions secrets):
  JOTFORM_API_KEY, JOTFORM_FORM_ID, DISCORD_WEBHOOK_URL, DISCORD_USER_ID
Question IDs (find them with `python remind.py --show-fields`):
  DATE_ADOPTED_QID, NOTES_QID, STATUS_QID
Only submissions whose status field equals REQUIRED_STATUS (default "Adopted",
set via the STATUS_VALUE env var; case-insensitive) get reminders.
"""
import os
import sys
from datetime import date, datetime

import requests

API_KEY = os.environ["JOTFORM_API_KEY"]
FORM_ID = os.environ["JOTFORM_FORM_ID"]
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
USER_ID = os.environ.get("DISCORD_USER_ID", "")
DATE_QID = os.environ.get("DATE_ADOPTED_QID", "")
NOTES_QID = os.environ.get("NOTES_QID", "")
STATUS_QID = os.environ.get("STATUS_QID", "")
REQUIRED_STATUS = os.environ.get("STATUS_VALUE", "Adopted").strip().lower()

# Use https://eu-api.jotform.com if your Jotform account is in the EU
BASE = os.environ.get("JOTFORM_BASE", "https://api.jotform.com")
REMIND_AFTER_DAYS = (7, 14)


def get_submissions():
    out, offset = [], 0
    while True:
        r = requests.get(
            f"{BASE}/form/{FORM_ID}/submissions",
            params={"apiKey": API_KEY, "limit": 1000, "offset": offset},
            timeout=30,
        )
        r.raise_for_status()
        batch = r.json()["content"]
        out.extend(batch)
        if len(batch) < 1000:
            return out
        offset += 1000


def show_fields():
    """Print question IDs and labels so you can fill in the QIDs."""
    r = requests.get(f"{BASE}/form/{FORM_ID}/questions", params={"apiKey": API_KEY}, timeout=30)
    r.raise_for_status()
    for qid, q in r.json()["content"].items():
        print(f"QID {qid}: {q.get('text')} ({q.get('type')})")


def parse_date(answer):
    """Date fields can come back as a string or a dict; handle both."""
    if not answer:
        return None
    if isinstance(answer, dict):
        if answer.get("datetime"):
            answer = answer["datetime"]
        else:
            try:
                return date(int(answer["year"]), int(answer["month"]), int(answer["day"]))
            except (KeyError, ValueError):
                return None
    text = str(answer).strip()
    for fmt in ("%Y-%m-%d %H:%M:%S", "%Y-%m-%d", "%m-%d-%Y", "%d-%m-%Y", "%m/%d/%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def answer_text(answers, qid):
    a = answers.get(qid, {}).get("answer")
    return a.strip() if isinstance(a, str) else ""


def main():
    if "--show-fields" in sys.argv:
        show_fields()
        return

    today = date.today()
    for sub in get_submissions():
        if sub.get("status") != "ACTIVE":
            continue
        answers = sub.get("answers", {})
        if answer_text(answers, STATUS_QID).lower() != REQUIRED_STATUS:
            continue
        adopted =parse_date(answers.get(DATE_QID, {}).get("answer"))
        if not adopted:
            continue

        days_since = (today - adopted).days
        if days_since not in REMIND_AFTER_DAYS:
            continue

        notes = answer_text(answers, NOTES_QID) or "(no notes)"
        message = (
            f"<@{USER_ID}> Reminder: it's been **{days_since} days** since adoption "
            f"({adopted:%d %b %Y}). Please send the vet records.\n"
            f"Notes: {notes}"
        )
        r = requests.post(WEBHOOK, json={"content": message}, timeout=30)
        r.raise_for_status()
        print(f"Sent {days_since}-day reminder for submission {sub['id']}")


if __name__ == "__main__":
    main()
