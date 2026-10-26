"""
Check Jotform submissions and post ONE Discord message (tagging the vet-records
person) listing every record that is 'Adopted' and at least MIN_DAYS (default 7)
past its 'Date Adopted'. Each line includes the Notes field (which has the cat's name).

It keeps listing a record on every run until its status changes, or (optional) until
the 'Vet records received' field is filled in. Schedule it to run every other day.

Config comes from environment variables (set as GitHub Actions secrets):
  JOTFORM_API_KEY, JOTFORM_FORM_ID, DISCORD_WEBHOOK_URL, DISCORD_USER_ID
Question IDs (find them with `python remind.py --show-fields`):
  DATE_ADOPTED_QID, NOTES_QID, STATUS_QID
  RECORDS_QID  (optional: if set, records where this field is filled in are skipped)
Other settings:
  STATUS_VALUE (default "Adopted", case-insensitive), MIN_DAYS (default 7),
  LOG_LEVEL (DEBUG, INFO, WARN, ERROR; default INFO)

Logging: every log line is passed through redact(). API keys and the webhook URL are
hidden completely, IDs show only their last 4 characters, and notes / cat names /
Discord message text are never logged.
"""
import os
import re
import sys
import time
from collections import Counter
from datetime import date, datetime, timezone

import requests

API_KEY = os.environ.get("JOTFORM_API_KEY", "")
FORM_ID = os.environ.get("JOTFORM_FORM_ID", "")
WEBHOOK = os.environ.get("DISCORD_WEBHOOK_URL", "")
USER_ID = os.environ.get("DISCORD_USER_ID", "")
DATE_QID = os.environ.get("DATE_ADOPTED_QID", "")
NOTES_QID = os.environ.get("NOTES_QID", "")
STATUS_QID = os.environ.get("STATUS_QID", "")
RECORDS_QID = os.environ.get("RECORDS_QID", "")  # optional
REQUIRED_STATUS = os.environ.get("STATUS_VALUE", "Adopted").strip().lower()
MIN_DAYS = int(os.environ.get("MIN_DAYS", "7") or "7")

# Use https://eu-api.jotform.com if your Jotform account is in the EU
BASE = os.environ.get("JOTFORM_BASE", "https://api.jotform.com")
DISCORD_LIMIT = 1900  # Discord messages max out at 2000 characters

# ---------------------------------------------------------------- logging ----
LEVELS = {"DEBUG": 10, "INFO": 20, "WARN": 30, "ERROR": 40}
THRESHOLD = LEVELS.get(os.environ.get("LOG_LEVEL", "INFO").strip().upper(), 20)


def mask_id(value):
    """Show only the last 4 characters of an ID."""
    s = str(value or "")
    return "***" + s[-4:] if len(s) > 8 else ("***" if s else "(empty)")


def redact(text):
    """Remove anything sensitive from a string before it is printed."""
    text = str(text)
    # patterns first, so they work even for values we don't know about
    text = re.sub(r"(?i)(api_?key=)[^&\s'\"]+", r"\1***", text)
    text = re.sub(r"(?i)(discord(?:app)?\.com/api/webhooks/)\S+", r"\1***", text)
    # then the exact secret values we were given
    for secret in (WEBHOOK, API_KEY):
        if secret:
            text = text.replace(secret, "***")
    for ident in (FORM_ID, USER_ID):
        if ident and len(ident) >= 4:
            text = text.replace(ident, mask_id(ident))
    return text


def log(level, msg):
    if LEVELS[level] >= THRESHOLD:
        stamp = datetime.now(timezone.utc).strftime("%H:%M:%S")
        print(f"{stamp}Z {level:<5} {redact(msg)}", flush=True)


def short(value, n=40):
    """Truncate a value so a surprising field can't flood or leak into the log."""
    s = repr(value)
    return s if len(s) <= n else s[: n - 3] + "..."


# ------------------------------------------------------------------- http ----
def http(method, label, url, **kw):
    """One HTTP call. On any failure, log a redacted reason and exit non-zero."""
    start = time.monotonic()
    try:
        r = requests.request(method, url, timeout=30, **kw)
    except requests.RequestException as e:
        log("ERROR", f"{label}: request failed ({type(e).__name__}): {e}")
        sys.exit(1)
    ms = int((time.monotonic() - start) * 1000)
    if not r.ok:
        log("ERROR", f"{label}: HTTP {r.status_code} in {ms}ms: {r.text[:200]!r}")
        sys.exit(1)
    log("INFO", f"{label}: HTTP {r.status_code} in {ms}ms")
    return r


def jotform_get(label, path, params=None):
    p = {"apiKey": API_KEY}
    p.update(params or {})
    r = http("GET", label, f"{BASE}{path}", params=p)
    try:
        data = r.json()
    except ValueError:
        log("ERROR", f"{label}: response was not JSON")
        sys.exit(1)
    code = data.get("responseCode")
    if code not in (None, 200):
        log("ERROR", f"{label}: Jotform responseCode {code}: {data.get('message')}")
        sys.exit(1)
    return data["content"]


def get_submissions():
    out, offset = [], 0
    while True:
        batch = jotform_get("Jotform submissions", f"/form/{FORM_ID}/submissions",
                            {"limit": 1000, "offset": offset})
        out.extend(batch)
        if len(batch) < 1000:
            return out
        offset += 1000


def show_fields():
    """Print question IDs and labels so you can fill in the QIDs."""
    for qid, q in jotform_get("Jotform questions", f"/form/{FORM_ID}/questions").items():
        print(f"QID {qid}: {q.get('text')} ({q.get('type')})")


def show_status():
    """Print the Status question's definition and the raw status values seen, to work
    out how option IDs like '{abc123}' map to labels like 'Adopted'."""
    import json
    questions = jotform_get("Jotform questions", f"/form/{FORM_ID}/questions")
    print(f"--- Status question {STATUS_QID} definition ---")
    print(redact(json.dumps(questions.get(STATUS_QID), indent=2)))
    values, example = Counter(), None
    for sub in get_submissions():
        ans = sub.get("answers", {}).get(STATUS_QID)
        if ans:
            values[repr(ans.get("answer"))] += 1
            example = example or ans
    print("--- Raw status values (count) ---")
    for v, n in values.most_common():
        print(f"{n:5}  {v}")
    print("--- One full status answer object ---")
    print(redact(json.dumps(example, indent=2)))

    # The status column may be a Jotform Tables column rather than a form question,
    # so look for where its option IDs are defined in the form properties.
    ids = {v.strip("'\"{}") for v in values if v.startswith(("'{", '"{'))}
    props = jotform_get("Jotform properties", f"/form/{FORM_ID}/properties")

    def search(node, path):
        if isinstance(node, dict):
            items = node.items()
        elif isinstance(node, list):
            items = enumerate(node)
        else:
            if isinstance(node, str) and any(i in node for i in ids):
                print(f"{path}: {node[:500]}")
            return
        for k, v in items:
            if str(k) in ids:
                print(f"{path}/{k}: {json.dumps(v)[:500]}")
            search(v, f"{path}/{k}")

    print(f"--- Where the {len(ids)} status IDs appear in form properties ---")
    search(props, "")
    print("--- Top-level property keys ---")
    print(", ".join(sorted(props)) if isinstance(props, dict) else type(props).__name__)


# --------------------------------------------------------------- parsing ----
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


def has_value(answers, qid):
    """True if the field is filled in (text, checkbox list, file list, etc.)."""
    a = answers.get(qid, {}).get("answer")
    if isinstance(a, str):
        return bool(a.strip())
    return bool(a)


# --------------------------------------------------------------- discord ----
def send_discord(lines):
    """Send one message (split only if it would exceed Discord's length limit)."""
    header = f"<@{USER_ID}> Vet records still needed for these adopted cats:"
    chunks, current = [], header
    for line in lines:
        if len(current) + len(line) + 1 > DISCORD_LIMIT:
            chunks.append(current)
            current = "(continued)"
        current += "\n" + line
    chunks.append(current)
    for i, chunk in enumerate(chunks, 1):
        http("POST", f"Discord webhook (message {i}/{len(chunks)})", WEBHOOK,
             json={"content": chunk})


# ------------------------------------------------------------------ main ----
def main():
    if "--show-fields" in sys.argv:
        show_fields()
        return
    if "--show-status" in sys.argv:
        show_status()
        return

    started = time.monotonic()
    log("INFO", f"Run start. Form {mask_id(FORM_ID)}; status filter '{REQUIRED_STATUS}'; "
                f"min days {MIN_DAYS}; vet-records field "
                f"{'configured' if RECORDS_QID else 'not configured'}.")

    required = (("JOTFORM_API_KEY", API_KEY), ("JOTFORM_FORM_ID", FORM_ID),
                ("DISCORD_WEBHOOK_URL", WEBHOOK), ("DISCORD_USER_ID", USER_ID),
                ("DATE_ADOPTED_QID", DATE_QID), ("NOTES_QID", NOTES_QID),
                ("STATUS_QID", STATUS_QID))
    missing = [name for name, val in required if not val]
    for name in missing:
        log("ERROR", f"{name} is empty - check the GitHub secret of that name")
    if missing:
        sys.exit(1)
    if not USER_ID.isdigit():
        log("WARN", "DISCORD_USER_ID is not a plain number, so the ping may not work "
                    "(use Discord's 'Copy User ID', not the username)")

    today = date.today()
    subs = get_submissions()
    log("INFO", f"Today (UTC) {today}; fetched {len(subs)} submissions.")

    skipped = Counter()
    qids_seen = set()
    overdue = []  # (days_since, line)
    for sub in subs:
        sid = mask_id(sub.get("id"))
        answers = sub.get("answers", {})
        qids_seen.update(answers.keys())

        if sub.get("status") != "ACTIVE":
            skipped["deleted/archived submission"] += 1
            log("DEBUG", f"[{sid}] skipped: submission is {sub.get('status')}")
            continue
        status_val = answer_text(answers, STATUS_QID)
        if status_val.lower() != REQUIRED_STATUS:
            skipped["status is not Adopted"] += 1
            log("DEBUG", f"[{sid}] skipped: status {short(status_val)}")
            continue
        raw_date = answers.get(DATE_QID, {}).get("answer")
        adopted = parse_date(raw_date)
        if not adopted:
            skipped["adoption date missing/unreadable"] += 1
            log("WARN", f"[{sid}] skipped: could not read adoption date (value: {short(raw_date)})")
            continue
        days_since = (today - adopted).days
        if days_since < MIN_DAYS:
            skipped[f"adopted less than {MIN_DAYS} days ago"] += 1
            log("DEBUG", f"[{sid}] skipped: only {days_since} days since adoption")
            continue
        if RECORDS_QID and has_value(answers, RECORDS_QID):
            skipped["vet records already received"] += 1
            log("DEBUG", f"[{sid}] skipped: vet records already received")
            continue

        notes = " ".join((answer_text(answers, NOTES_QID) or "(no notes)").split())
        if len(notes) > 300:
            notes = notes[:297] + "..."
        log("INFO", f"[{sid}] eligible: {days_since} days since adoption")
        overdue.append((days_since, f"- **{days_since} days** (adopted {adopted:%d %b %Y}): {notes}"))

    # a question ID that appears in no submission at all is almost certainly wrong
    for name, qid in (("DATE_ADOPTED_QID", DATE_QID), ("NOTES_QID", NOTES_QID),
                      ("STATUS_QID", STATUS_QID), ("RECORDS_QID", RECORDS_QID)):
        if qid and subs and qid not in qids_seen:
            log("WARN", f"{name} '{qid}' does not appear in any submission - wrong question ID?")

    breakdown = ", ".join(f"{n} {reason}" for reason, n in skipped.most_common()) or "none"
    log("INFO", f"Summary: {len(subs)} fetched, {len(overdue)} eligible; skipped: {breakdown}.")

    if overdue:
        overdue.sort(key=lambda x: -x[0])  # longest overdue first
        send_discord([line for _, line in overdue])
        log("INFO", f"Reminder sent covering {len(overdue)} record(s).")
    else:
        log("INFO", "Nothing overdue, no message sent.")
    log("INFO", f"Done in {int((time.monotonic() - started) * 1000)}ms.")


if __name__ == "__main__":
    main()
