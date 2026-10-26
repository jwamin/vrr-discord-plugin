# Cat rescue: vet records reminder

Every day, posts ONE Discord message (tagging the people who send vet records)
listing every record whose Status is "Adopted" and whose "Date Adopted" is 7 or more
days ago. Each line includes the adoption date and the Notes field (which contains the
cat's name), longest overdue first.

A record keeps appearing on every run until its Status changes, or (recommended) until
a "Vet records received" field is filled in. If nothing is overdue, no message is sent.

It runs on GitHub Actions (free). Nothing needs hosting.

## Files
- `remind.py` - the script
- `.github/workflows/remind.yml` - schedule (daily, 13:00 UTC, about 9am US Eastern)

## Setup
1. In Jotform, add a "Date Adopted" date field to the form (it appears as a table column).
   Recommended: also add a "Vet records received" field (e.g. a short text or checkbox).
   Once it has any value, that record stops being reminded.
2. Discord: Channel settings > Integrations > Webhooks > New Webhook. Copy the URL.
3. Discord: turn on Developer Mode (User Settings > Advanced), right-click each person
   to notify and choose Copy User ID. This is what makes the message ping them. It must
   be the long number, not their username. To notify several people, put all their IDs
   in the `DISCORD_USER_ID` secret separated by commas, e.g. `123456789012345678,876543210987654321`.
4. Jotform: get an API key (Account Settings > API) and the form ID (in the form URL).
   EU accounts: set `JOTFORM_BASE` to `https://eu-api.jotform.com` in the workflow env.
5. Find the question IDs for "Date Adopted", "Notes", "Status" (and "Vet records received"):
   ```
   pip install requests
   JOTFORM_API_KEY=... JOTFORM_FORM_ID=... python remind.py --show-fields
   ```
6. Create a GitHub repo with these files, then add repository secrets
   (Settings > Secrets and variables > Actions):
   `JOTFORM_API_KEY`, `JOTFORM_FORM_ID`, `DISCORD_WEBHOOK_URL`, `DISCORD_USER_ID`,
   `DATE_ADOPTED_QID`, `NOTES_QID`, `STATUS_QID`
   Optional: `RECORDS_QID` (the "Vet records received" question ID). If you leave it
   unset, the script reminds until Status changes.
   Reminders only include records whose Status equals "Adopted" (case-insensitive).
   If your status option is worded differently, change `STATUS_VALUE` in the workflow.
   A Status column added in Jotform Tables returns option IDs like `{hjrru94ta7}`
   rather than text; the script translates these back to the option label for you.
7. Test: Actions tab > "Vet records reminder" > Run workflow, then open the run and
   read the "Run python remind.py" log (see Logging below). To force a test message,
   set `MIN_DAYS` in the workflow to "0", run it, then set it back to "7".

## Logging
Each run logs, in order: the settings in use, each Jotform/Discord call with its HTTP
status and timing, one line per eligible record, a summary such as
`Summary: 31 fetched, 5 eligible; skipped: 22 status is not Adopted, 4 adopted less
than 7 days ago`, and the total run time. Check that "eligible" matches the number of
records you expect.
- Log level is INFO by default. DEBUG also logs every skipped record and why.
  - One-off: Actions tab > "Vet records reminder" > Run workflow, pick `DEBUG`.
  - For scheduled runs too: Settings > Secrets and variables > Actions > Variables,
    add `LOG_LEVEL` = `DEBUG` (delete it to go back to INFO). Use a variable, not a
    secret: GitHub masks secret values, so a `DEBUG` secret turns every log level
    into `***`.
- Warnings point at likely mistakes: an empty secret, a Discord user ID that isn't a
  number, a question ID that appears in no submission, or an unreadable date.
- Any failed call (bad API key, wrong form ID, deleted webhook) prints the HTTP status
  and the service's error message, then the run fails (red) so it can't go unnoticed.
- Nothing sensitive is logged. API keys and the webhook URL are replaced by `***`,
  form / submission / Discord IDs show only their last 4 characters, and notes, cat
  names and the Discord message text are never printed. This is on top of GitHub's own
  masking of secrets.

## Notes
- GitHub pauses scheduled workflows in repos with no activity for 60 days. If the
  reminders stop, open the Actions tab and re-enable the workflow.
- Date fields can come back in different formats. `parse_date` handles the common
  ones; the run log shows the raw value when it can't read a date.
