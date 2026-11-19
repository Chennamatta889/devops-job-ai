# Auto Apply Agent

A dependency-free Python job discovery, skill matching and controlled email application agent. It does not use an LLM or invent resume facts.

## Setup
Prefer a private repository for job search activity. In Settings > Secrets and variables > Actions, add:
- PROFILE_JSON: JSON with name, skills (array), locations (array), max_required_years (number), minimum_match (80 recommended), max_per_run (5 recommended).
- GREENHOUSE_BOARDS: comma-separated employer board identifiers (optional).
- JOB_FEED_JSON: trusted array of job objects (optional). Each contains company, title, description, location, url. Add application_email and email_application_authorized: true only when the employer explicitly accepts applications at that address.
- SMTP_USER, SMTP_APP_PASSWORD: Gmail account and app password (only for email mode).
- RESUME_BASE64: base64 of your actual PDF resume (only for email mode; GitHub secret size limit applies).

Example profile (replace all values with verified facts):
```json
{"name":"Your Name","skills":["aws","jenkins","docker","kubernetes","openshift","linux","ci/cd","git"],"locations":["india","hyderabad","bengaluru","bangalore","pune","chennai","noida","gurugram","mumbai"],"max_required_years":3,"minimum_match":80,"max_per_run":5}
```

Set Actions repository variable AUTO_APPLY to true only after reviewing a dry-run and verifying the feed. Default false. Job descriptions are treated as data, not instructions. Public Greenhouse listings are discovery-only; portal applications are reported for manual handling. No CAPTCHA or authentication bypass. Email sending is restricted to explicit authorized addresses from your trusted feed. Do not use unsolicited recruiter lists.

The match score measures overlap with recognized technologies mentioned in the JD; it is not a hiring probability. Senior roles and experience/location mismatches are excluded conservatively. Unknown experience is review-only. The ledger stores hashed identities and status; reservations are pushed before sending to reduce duplicates, and ambiguous outcomes require manual review. Never run simultaneous local and Actions instances. Job reports may be visible in a public repository's Actions artifacts; use a private repository for sensitive searches.

Run locally: export PROFILE_JSON and optional source variables, then python auto_apply/agent.py. Run tests: python -m unittest discover -s auto_apply -p 'test_*.py'. The workflow runs at 10 AM and 6 PM IST approximately (GitHub schedules may be delayed).
