# Cat rescue: vet records reminder

Posts a Discord reminder (tagging the person who sends vet records) 7 and 14 days
after the "Date Adopted" on a Jotform submission, but only if the record's Status is
"Adopted". The message includes the Notes
field, which contains the cat's name.

It runs once a day on GitHub Actions (free). Nothing needs hosting.

## Files
- `remind.py` - the script
- `.github/workflows/remind.yml` - daily schedule (13:00 UTC, about 9am US Eastern)

## Setup
1. In Jotform, add a "Date Adopted" date field to the form (it appears as a table column).
2. Discord: Channel settings > Integrations > Webhooks > New Webhook. Copy the URL.
3. Discord: turn on Developer Mode (User Settings > Advanced), right-click the person
   and choose Copy User ID. This is what makes the message ping them.
4. Jotform: get an API key (Account Settings > API) and the form ID (in the form URL).
   EU accounts: set `JOTFORM_BASE` to `https://eu-api.jotform.com` in the workflow env.
5. Find the question IDs for "Date Adopted", "Notes" and "Status":
   ```
   pip install requests
   JOTFORM_API_KEY=... JOTFORM_FORM_ID=... python remind.py --show-fields
   ```
6. Create a GitHub repo with these files, then add repository secrets
   (Settings > Secrets and variables > Actions):
   `JOTFORM_API_KEY`, `JOTFORM_FORM_ID`, `DISCORD_WEBHOOK_URL`, `DISCORD_USER_ID`,
   `DATE_ADOPTED_QID`, `NOTES_QID`, `STATUS_QID`
   Reminders are only sent when the Status field equals "Adopted" (case-insensitive).
   If your status option is worded differently, change `STATUS_VALUE` in the workflow.
7. Test: Actions tab > "Vet records reminder" > Run workflow. To test the message
   itself, temporarily change `REMIND_AFTER_DAYS` in `remind.py` to match a real
   submission's age.

## Notes
- It only fires on exactly day 7 and day 14. If a daily run is skipped, that reminder
  is missed. For more robustness, add "7-day sent" / "14-day sent" columns and have
  the script check and update them.
- Date fields can come back in different formats. `parse_date` handles the common
  ones; print one real submission to confirm.
- Optional improvement: add a "Records received" column and skip those submissions.
