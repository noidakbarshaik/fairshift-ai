# Prompt Wars 2026 submission status

## Ready on the PENDRIVE

- Application source and Vercel configuration are in this folder.
- The local Git repository is on one branch: `main`.
- The committed source is far below the 10 MB limit.
- Automated checks pass locally; see the project README for test commands and known limitations.
- A LinkedIn post draft is in `README.md`.

## Links still to create

| Submission field | Status | Required form |
|---|---|---|
| GitHub repository | Not published yet | Public repository URL ending in `.git` |
| Live application | Not deployed yet | Vercel URL, if accepted by the organizers |
| LinkedIn project post | Draft only | Public post URL |

The local source is prepared, but GitHub repository creation/push and Vercel deployment were not completed in this session. Do not paste placeholder or guessed URLs into the Innovator Dashboard.

## Important conflict with the official submission guide

The Prompt Wars Submission Guide says Google Cloud Run is mandatory and explicitly says Vercel/Netlify links are rejected. Your later instruction allows Vercel, so the project is prepared for Vercel; that may make the final submission ineligible unless the organizers confirm the exception. The app source also includes a Dockerfile for a future container deployment, but that alone does not satisfy Cloud Run hosting.

The same guide says the GitHub repository must be public, contain exactly one branch, and be strictly under 10 MB. It asks for a LinkedIn post that explains the problem, build, and solution fit. Innovator Dashboard submission uses the registered hackathon email and asks for GitHub, hosted app, and LinkedIn links. It allows at most two attempts; the latest attempt replaces the previous score. Submit only after all public links work, then confirm the dashboard recorded the attempt.

## Cloud credits guide

The Cloud Resources Guide describes redeeming credits through the provided `trygcp.dev` link, using the same Gmail account as Google Cloud Console, creating a Cloud project, linking the Google Cloud Platform Trial Billing account, and checking **Billing → Credits**. These steps are not needed for the requested Vercel path. If the contest requires Cloud Run, redeeming credits may help with the required hosting account.

## Next actions

1. Create an empty public GitHub repository named `fairshift-ai`; push the existing `main` branch using the commands in `README.md`.
2. Connect the repository to Vercel and provision a Postgres database; set `DATABASE_URL`, `FAIRSHIFT_SECRET`, `ENVIRONMENT=production`, and `COOKIE_SECURE=1` in deployment settings.
3. Verify the deployed worker and admin flows using fictional demo data.
4. Insert the real GitHub and deployment URLs into the LinkedIn draft, publish it, then copy its public URL.
5. Confirm with the organizers whether Vercel is acceptable despite the guide; otherwise deploy the Dockerized app to Cloud Run.
6. Submit the actual links using the registered hackathon email and verify the dashboard status.
