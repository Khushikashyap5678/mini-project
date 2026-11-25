# Campus Meeting Planner

A Flask and SQLite college project for requesting and approving campus appointments. The local demo uses a shared student dashboard and a separate teacher sign-in.

## Start on Windows

Extract the ZIP and open PowerShell in the folder that contains `app.py`. Run:

```powershell
python -m pip install -r requirements.txt
$env:TEACHER_PASSWORD = 'choose-a-teacher-password'
python app.py
```

Choose your own password. Set it again if you start the server from a new terminal. Open http://127.0.0.1:5000 in your browser. Press `Ctrl+C` in PowerShell to stop the server. If port 5000 is already in use, run `$env:CAMPUS_PORT = '5055'` before starting the app and open http://127.0.0.1:5055.

## Bring over existing appointments

The ZIP includes the database from the supplied project at `instance/appointments.db`. On the first run, older booked records enter the pending queue. Cancelled records keep their status. If you copy in a database from an older version, the app adds any missing fields when it starts.

## Try a booking

1. Choose **Request appointment** or select a campus department from the dashboard.
2. Enter a title and a future date and time in India Standard Time. Pick a reminder interval or select **Off**.
3. Open **Teacher review**, sign in with the password you set, and click **Approve** on the request.
4. Return to **My schedule** to see the approved status. You can search, filter, edit, cancel, or choose a date on the calendar. Changes to an approved request send it back for review.
5. Check **Reminders** during the chosen alert window. Download the `.ics` file after approval to import the appointment into a calendar app that supports imported alerts.

The portal calculates reminders when the dashboard loads. Calendar exports use a 30-minute event duration. Booking and cancellation change the local project database only. An imported calendar event can be updated or removed separately in your calendar app.

## Project structure

| Path | Purpose |
| --- | --- |
| `app.py` | Booking, validation, reminder calculations, migration and calendar export |
| `templates/` | Dashboard, booking form and shared layout |
| `static/` | Responsive layout, cancellation dialog and live form preview |
| `instance/appointments.db` | SQLite database included in the ZIP |
