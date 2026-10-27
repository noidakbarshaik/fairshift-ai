# FairShift AI — Decent Work Platform

A mobile-first prototype for clearer attendance and pay records, safer workplace reporting, and evidence-based employer oversight. It uses one shared backend for fictional construction and campus-facilities organisations.

## What works

- **Worker workspace:** secure demo sign-in, server-timestamped check-in/check-out, attendance history, deterministic hours/overtime/pay calculation, safety reports, report status history, and anonymous report tracking by private code.
- **Employer workspace:** organization/industry selection, attendance and overtime metrics calculated from saved database records, safety queue and status updates, worker directory, configurable demo pay assumptions, and an optional AI summary.
- **Privacy:** worker endpoints are role-protected; workers see only their own attendance and identified reports. Anonymous reports are stored without a reporter user ID and are rendered as Anonymous in admin views. The report tracking code is stored as a one-way hash. This does not promise anonymity from system operators.
- **Reliability:** duplicate active check-ins are rejected and constrained by a partial unique database index; invalid check-outs are rejected; overnight elapsed times use server timestamps; the deterministic summary stays available if Gemini is unavailable.
- **Accessibility:** responsive layout, labeled forms, keyboard focus styling, status text, and reduced-motion support. The language switch translates a useful subset of common worker-screen text to Tamil; it is not yet a complete Tamil localization.

All people, organizations, sessions, and reports shown at first run are fictional sample data. Demo accounts share the password `FairShiftDemo26!`; this is strictly for a disposable demo, never production worker information.

## Run locally

Python 3.12 is recommended. From this folder:

```powershell
py -3.12 -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -r requirements.txt
$env:DATABASE_URL = "sqlite:///./fairshift.db"
$env:FAIRSHIFT_SECRET = "replace-with-a-long-random-value"
python -m uvicorn main:app --reload --port 8080
```

Open `http://127.0.0.1:8080`.

Demo logins:

| Role | Email | Password |
|---|---|---|
| Admin | `admin@fairshift.demo` | `FairShiftDemo26!` |
| Construction worker | `worker@fairshift.demo` | `FairShiftDemo26!` |
| Campus worker | `campus@fairshift.demo` | `FairShiftDemo26!` |

Other seeded worker accounts: `siteworker@fairshift.demo` and `campusworker@fairshift.demo`.

The database seeds the two demo organizations, worker accounts, example shifts, and example reports only when the organizations table is empty. For a clean local demo reset, stop the server and delete `fairshift.db`.

## Pay assumptions

The initial example uses an 8-hour standard shift and a 1.5 overtime multiplier, configurable by an admin for each demo organization. Break deductions are zero unless a worker enters a break at checkout. Estimated gross pay is regular hours × hourly rate plus overtime hours × hourly rate × multiplier. No taxes or statutory deductions are invented; this is not a legal calculation or take-home pay estimate.

## Optional AI

Set `GEMINI_API_KEY` in the server environment to enable a Gemini summary of aggregate dashboard metrics and category/status counts. Personal names, emails, report descriptions, and individual records are excluded from that request. The normal database-derived summary remains available when no key is configured or the AI service fails. The AI response is advisory; numeric metrics remain application-calculated. Never put the key in browser code or source control.

## Tests

Install runtime dependencies, then run:

```powershell
python -m unittest discover -s tests -v
node --check static\app.js
```

The tests cover login/roles, duplicate check-ins, check-out, deterministic pay, missing rates, overnight shifts, anonymous report privacy/tracking, status history, and industry-specific dashboard metrics.

## Deploy to Vercel

The FastAPI app is exposed through `index.py`, and Vercel supports FastAPI and managed Postgres integrations. Do not use SQLite for a serverless deployment because its function filesystem is not a durable shared database.

1. Create a GitHub repository and push this project.
2. Import the repository into Vercel.
3. Add a Postgres integration (for example, Neon through Vercel Marketplace) and set its connection string as `DATABASE_URL`.
4. Set `ENVIRONMENT=production`, `COOKIE_SECURE=1`, and `FAIRSHIFT_SECRET` to a long random value in Vercel environment settings. Optionally set `GEMINI_API_KEY` and `GEMINI_MODEL`.
5. Deploy and verify `/health`, the worker flow, and admin flow using the demo data. Check the Vercel function logs if startup fails.

Vercel’s FastAPI runtime is documented at [vercel.com/docs/frameworks/backend/fastapi](https://vercel.com/docs/frameworks/backend/fastapi). Postgres integrations are described at [vercel.com/docs/marketplace-storage](https://vercel.com/docs/marketplace-storage).

**Contest submission note:** the supplied Prompt Wars Submission Guide explicitly requires a Google Cloud Run URL and says Vercel/Netlify links are rejected. Your latest instruction allows Vercel, so this project is prepared for Vercel. If submitting to that contest, verify with the organizers whether this change is accepted; a Vercel deployment does not satisfy the guide as written.

## GitHub submission checks

The guide requires a public repository URL ending in `.git`, exactly one branch, and repository size strictly under 10 MB. Before submission, verify with `git branch --list` and `git count-objects -vH`; then push only the intended branch and paste the `.git` URL into the Innovator Dashboard.

## LinkedIn post draft

> We built FairShift AI for Prompt Wars 2026 and UN SDG 8: Decent Work and Economic Growth. Many employee-intensive workplaces still depend on paper registers and scattered messages, leaving workers unsure about hours and pay and making safety concerns hard to track.
>
> FairShift brings attendance, transparent example pay calculations, private safety reporting, status follow-up, and employer workforce insights into one mobile-friendly platform. The same setup supports construction teams and campus facilities through configurable organizations, locations, and safety categories.
>
> The prototype uses server-recorded attendance and deterministic pay calculations. Sample organizations and records are fictional. Anonymous reports hide the reporter in ordinary admin screens, while the project is clear that this is not absolute anonymity from system operators.
>
> Project: [add the live deployment link] · Code: [add the public GitHub .git link]
>
> #SDG8 #DecentWork #WorkerSafety #ResponsibleAI #PromptWars2026

After publishing the post, copy its public LinkedIn URL into the Innovator Dashboard along with the repository and deployed app links. The guide says to use the registered hackathon email, submit at most twice, and verify the dashboard recorded the submission; a later attempt replaces the prior score.

## Known limitations

- This is a hackathon demo, not a production workforce/payroll system.
- Demo accounts use a shared password; real user provisioning, password reset, MFA, account lockout/rate limits, and organization-admin onboarding need implementation before real worker data is allowed.
- Anonymous reports are de-linked from user IDs in the app database but cannot guarantee anonymity from hosting/database operators or network metadata.
- Tamil is a partial interface translation; no voice support or claim of complete Tamil coverage is made.
- No image attachments, shift scheduling, skills passport, legal payroll rules, or admin worker-management CRUD are implemented.
- The optional AI summary has a deterministic fallback and has not been connected to a production Gemini account unless a key is configured.
- Vercel and database accounts are required to create a live deployment; GitHub publishing, LinkedIn posting, and Innovator Dashboard submission require the user's connected accounts/actions.
