AttendAI Login and Role-Based Access Update
===========================================

This package adds login and role-based access to the current subject-wise, maroon-themed AttendAI project while keeping the existing motion-only attendance challenge (anti-spoof blocking remains disabled, per the project configuration).

Install:
1. Stop Flask with Ctrl+C.
2. Back up the current project folder.
3. Extract this ZIP to C:\Users\Lenovo\Desktop\AttendAI and replace included files.
4. Run: python app.py
5. Open http://127.0.0.1:5000/
6. On first launch, create an administrator account at the one-time setup page. Use a username and a password with at least 10 characters. No default credentials are provided.
7. Sign in, open Accounts & Roles, and create faculty accounts.

Roles:
- Administrator: manages students, subjects, settings and accounts; can also take attendance and view reports.
- Faculty: can access the dashboard, student directory, live attendance and reports. Faculty cannot enroll/delete students, create subjects or change system settings.

Security notes:
- Passwords are stored as Werkzeug hashes.
- Session cookies are HTTP-only and SameSite=Lax.
- A persistent secret key is generated in .attendai_session_key (or ATTENDAI_SECRET_KEY can be set in the environment).
- POST requests require a CSRF token.
- This is for a localhost hackathon prototype. Before deployment to other computers, use HTTPS and conduct a security review.

The package does not include / replace models, data/students, attendance files, or attendai.db. Existing data should remain in place.
