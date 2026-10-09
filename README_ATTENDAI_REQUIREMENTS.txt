ATTENDAI — REQUIREMENTS COMPLETION UPDATE

Includes functional routes/pages for:
1. Browser live camera face detection and face recognition (YuNet + SFace from existing project).
2. Automatic attendance marking only after both anti-spoof screening and randomized head-movement challenge pass.
3. SQLite student metadata, sessions, attendance records and settings. Existing .npz face templates remain in data/students.
4. One attendance record per student per date enforced by SQLite primary key; liveness/anti-spoof state resets per browser camera session. Anti-spoofing is a prototype deterrent, not a guarantee.
5. Faculty dashboard with registered, present, absent, attendance rate, recent attendance and low-attendance alerts.
6. Daily, weekly, monthly and custom date-range reports.
7. PDF and CSV exports for the selected report range.
8. Low-attendance in-app alerts; optional email delivery when student emails and SMTP environment settings are configured.

INSTALLATION
1. Stop Flask with Ctrl+C.
2. Make sure a backup of AttendAI exists before replacing files.
3. Extract this ZIP into C:\Users\Lenovo\Desktop\AttendAI and replace included files when prompted.
4. Do not delete data/, models/, attendance/, or other existing src files.
5. Install the PDF library if not installed:
   python -m pip install reportlab
6. Run:
   python app.py
7. Open http://127.0.0.1:5000
8. Visit the Reports page and test Daily, Weekly, Monthly and Custom ranges. Download both CSV and PDF.

DATA MIGRATION
On startup, AttendAI creates attendai.db and imports existing data from data/students/*.npz and attendance/attendance_YYYY-MM-DD.csv. Existing daily CSV files are preserved. New web attendance is saved to SQLite and mirrored into its daily CSV file. Do not delete the database if you want to retain database metadata, settings and notifications-related configuration.

LOW-ATTENDANCE EMAIL (OPTIONAL)
Email alerts need student email addresses and SMTP credentials. The app does not store an SMTP password in the database. Set in the same PowerShell window before starting the app, using real values provided by your mail provider:
  $env:ATTENDAI_SMTP_HOST="smtp.example.com"
  $env:ATTENDAI_SMTP_PORT="587"
  $env:ATTENDAI_SMTP_USERNAME="your-account"
  $env:ATTENDAI_SMTP_PASSWORD="your-app-password"
  $env:ATTENDAI_SMTP_FROM="attendance@example.com"
Use app passwords where required. Never publish these values. Without SMTP config, in-app low-attendance alerts still work.

LIMITATIONS
This is a localhost hackathon prototype. It is not a hardened production application: faculty login/roles, HTTPS, CSRF protection, formal consent/retention handling, encrypted backup, robust camera hardware attestation, and validated anti-spoof benchmarks are still needed before institutional deployment. Anti-spoof scores can produce false accepts and false rejects; test on the actual webcam with consenting live subjects, print photos and screen replay videos.
