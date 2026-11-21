# Cat rescue: vet records reminder

Every Monday, Wednesday and Friday morning, posts ONE Discord message (tagging the people who send vet records)
listing every record whose Status is "Adopted" and whose "Date Adopted" is 7 or more
days ago. Each line includes the adoption date and the Notes field (which contains the
cat's name), longest overdue first.

A record keeps appearing on every run until its Status changes, or (recommended) until
a "Vet records received" field is filled in. If nothing is overdue, no message is sent.

The script runs on GitHub Actions (free). A small launchd job on a Mac starts it at
8:30am New York time, because GitHub's own scheduler started runs 4-9 hours late
(see Scheduling below).

## Files
- `remind.py` - the script
- `.github/workflows/remind.yml` - the GitHub Actions workflow (its own schedule is
  commented out; runs are started manually or by launchd)
- `launchd/trigger-remind.sh` - starts the workflow, with day/time and once-a-day checks
- `launchd/com.jwamin.vrr-remind.plist` - runs that script Mon/Wed/Fri on a Mac

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
   Optional: `NTFY_TOPIC` to get a phone/desktop notification every time the job runs
   (see below).
7. Test: Actions tab > "Vet records reminder" > Run workflow, then open the run and
   read the "Run python remind.py" log (see Logging below). To force a test message,
   set `MIN_DAYS` in the workflow to "0", run it, then set it back to "7".
8. Install the launchd job on the Mac that will start the runs (see Scheduling below).

## Scheduling (launchd on a Mac)
GitHub's scheduled runs started 4-9 hours late (a 9am run typically arrived around
4:40pm), but runs started on demand begin within seconds. So a launchd job on a Mac
starts the workflow at 8:30am New York time Mon/Wed/Fri, with retries at 9:00 and 9:30.
`launchd/trigger-remind.sh` only starts the workflow if:
- it's Mon/Wed/Fri between 8 and 10am New York time. launchd runs a missed time
  when the Mac wakes up, which could be hours later.
- the workflow hasn't already run that day (failed or cancelled runs don't count),
  so the 9:00 and 9:30 times are retries, not extra reminders.

It uses the Mac's GitHub CLI login (`gh auth login`, needs the `workflow` scope), so
there is no extra token to manage. The Mac's time zone should be New York.

Install:
```
cp launchd/com.jwamin.vrr-remind.plist ~/Library/LaunchAgents/
launchctl bootstrap gui/$(id -u) ~/Library/LaunchAgents/com.jwamin.vrr-remind.plist
```
Uninstall:
```
launchctl bootout gui/$(id -u)/com.jwamin.vrr-remind
rm ~/Library/LaunchAgents/com.jwamin.vrr-remind.plist
```
- Check it: `launchd/trigger-remind.sh --dry-run --force` runs every check without
  starting anything (`--force` ignores the day/time window).
- Log: `~/Library/Logs/vrr-remind-trigger.log`
- An asleep Mac is fine (the retries cover it). If the Mac is off or away from 8 to
  10am, that day is skipped. `sudo pmset repeat wake MWF 08:25:00` wakes it for the run.
- The plist and script hard-code paths (`/Users/jossy/...`, `/opt/homebrew/bin/gh`).
  Edit them if the repo or `gh` lives elsewhere.
- To go back to GitHub's own schedule, uncomment `schedule:` in the workflow and
  uninstall the launchd job. Don't use both at once, or people get two reminders.

## Run notifications (ntfy.sh)
Every run can send a push notification through [ntfy.sh](https://ntfy.sh), so you
know the job ran without opening GitHub. A successful run sends its summary (counts
only, e.g. "Summary: 31 fetched, 2 eligible..." and "Reminder sent covering 2
record(s)."). A failed run sends a high-priority "Vet reminder FAILED" alert. Tapping
either notification opens the run's log.
1. Install the ntfy app (iOS / Android) or open https://ntfy.sh/app in a browser.
2. Make up a long, random topic name, e.g. `vrr-vet-7f3k9q2xw8`. Anyone who knows
   the name can read or post to it, so treat it like a password.
3. Subscribe to that topic in the app.
4. Add it as the repository secret `NTFY_TOPIC`. Without that secret, the
   notification step is skipped.

## Logging
Each run logs, in order: the settings in use, each Jotform/Discord call with its HTTP
status and timing, one line per eligible record, a summary such as
`Summary: 31 fetched, 5 eligible; skipped: 22 status is not Adopted, 4 adopted less
than 7 days ago`, and the total run time. Check that "eligible" matches the number of
records you expect.
- Log level is INFO by default. DEBUG also logs every skipped record and why.
  - One-off: Actions tab > "Vet records reminder" > Run workflow, pick `DEBUG`.
  - For every run started by launchd too: Settings > Secrets and variables > Actions > Variables,
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
- If the reminders stop, check the Mac first: is it on and logged in, is the job
  loaded (`launchctl print gui/$(id -u)/com.jwamin.vrr-remind`), and what does the log
  say?
- Date fields can come back in different formats. `parse_date` handles the common
  ones; the run log shows the raw value when it can't read a date.
