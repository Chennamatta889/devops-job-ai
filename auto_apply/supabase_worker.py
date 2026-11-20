"""Multi-user DraftflowAI Auto Apply worker backed by Supabase.

The service-role key is used only inside the private GitHub Actions runner.
This worker never prints candidate profile values, resume contents, tokens, or storage URLs.
It never bypasses CAPTCHA, MFA, login walls, or human-verification controls.
"""
from __future__ import annotations

import json
from io import BytesIO
from pypdf import PdfReader
import os
import re
from datetime import datetime, timezone
from urllib.parse import quote, urlparse

import requests

from portal import HOSTS, portal_apply
from screening import normalize

CONSENT_VERSION = "2026-11-v1"
MAX_SUBMISSIONS_PER_RUN = 5
PUBLIC_JOB_FEED_URL = os.getenv(
    "PUBLIC_JOB_FEED_URL",
    "https://raw.githubusercontent.com/Chennamatta889/devops-job-ai/main/data/jobs.json",
)
VERIFICATION_STATUS_URL = os.getenv(
    "VERIFICATION_STATUS_URL",
    "https://raw.githubusercontent.com/Chennamatta889/devops-job-ai/main/data/verification-status.json",
)


def configured() -> bool:
    return bool(
        os.getenv("SUPABASE_URL", "").strip()
        and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip()
    )


def base_url() -> str:
    return os.environ["SUPABASE_URL"].rstrip("/")


def headers(extra=None):
    key = os.environ["SUPABASE_SERVICE_ROLE_KEY"]
    result = {
        "apikey": key,
        "Authorization": f"Bearer {key}",
        "Content-Type": "application/json",
    }
    if extra:
        result.update(extra)
    return result


def rest_get(table: str, params: dict) -> list[dict]:
    response = requests.get(
        f"{base_url()}/rest/v1/{table}",
        headers=headers(),
        params=params,
        timeout=25,
    )
    response.raise_for_status()
    value = response.json()
    return value if isinstance(value, list) else []


def rest_insert(table: str, rows: list[dict]) -> None:
    if not rows:
        return
    response = requests.post(
        f"{base_url()}/rest/v1/{table}",
        headers=headers({"Prefer": "return=minimal"}),
        data=json.dumps(rows),
        timeout=25,
    )
    response.raise_for_status()


def patch_attempt(attempt_id: int, expected_status: str | None, values: dict) -> list[dict]:
    params = {"id": f"eq.{attempt_id}"}
    if expected_status:
        params["status"] = f"eq.{expected_status}"
    response = requests.patch(
        f"{base_url()}/rest/v1/application_attempts",
        headers=headers({"Prefer": "return=representation"}),
        params=params,
        data=json.dumps(values),
        timeout=25,
    )
    response.raise_for_status()
    value = response.json()
    return value if isinstance(value, list) else []


def ensure_resume_bucket() -> None:
    endpoint = f"{base_url()}/storage/v1/bucket/resumes"
    response = requests.get(endpoint, headers=headers(), timeout=20)
    if response.status_code == 200:
        return
    if response.status_code != 404:
        response.raise_for_status()

    created = requests.post(
        f"{base_url()}/storage/v1/bucket",
        headers=headers(),
        data=json.dumps(
            {
                "id": "resumes",
                "name": "resumes",
                "public": False,
                "file_size_limit": 6291456,
                "allowed_mime_types": ["application/pdf"],
            }
        ),
        timeout=20,
    )
    if created.status_code not in (200, 201):
        created.raise_for_status()
    print("Private resume bucket created.")


def fetch_public_json(url: str) -> dict:
    response = requests.get(url, timeout=25, headers={"User-Agent": "DraftflowAI/1.0"})
    response.raise_for_status()
    value = response.json()
    return value if isinstance(value, dict) else {}


def _norm(value) -> str:
    return re.sub(r"[^a-z0-9]+", " ", str(value or "").lower()).strip()


def _list(value) -> list[str]:
    if isinstance(value, list):
        return [str(x).strip() for x in value if str(x).strip()]
    return [x.strip() for x in str(value or "").split(",") if x.strip()]


SKILL_RULES = [["AWS","aws|amazon web services"],["Azure","azure"],["GCP","gcp|google cloud"],["Jenkins","jenkins"],["OpenShift","openshift|ocp"],["Docker","docker"],["Kubernetes","kubernetes|k8s"],["Terraform","terraform"],["Linux","linux"],["Python","python"],["Bash","bash"],["PowerShell","powershell"],["GitHub Actions","github actions"],["Git","git"],["CI/CD","ci\\s*[/\\-]\\s*cd|continuous integration|continuous delivery"],["IAM","iam"],["Ansible","ansible"],["Prometheus","prometheus"],["Grafana","grafana"],["ArgoCD","argo\\s*cd"],["JFrog","jfrog|artifactory"],["Dynatrace","dynatrace"],["Splunk","splunk"],["Java","java"],["Spring Boot","spring boot"],[".NET","\\.net|dotnet"],["C#","c#"],["JavaScript","javascript"],["TypeScript","typescript"],["React","react"],["Node.js","node\\.?js"],["SQL","sql"],["PostgreSQL","postgresql|postgres"],["MySQL","mysql"],["Redis","redis"],["Kafka","kafka"],["ETL","etl"],["Selenium","selenium"],["Playwright","playwright"],["Go","golang"]]
ROLE_RULES = [["DevOps Engineer","devops"],["Site Reliability Engineer","site reliability engineer|\\bsre\\b"],["Cloud Engineer","cloud engineer|cloud devops"],["Platform Engineer","platform engineer"],["Infrastructure Engineer","infrastructure engineer"],[".NET Developer","\\.net developer|dotnet developer|c# developer"],["Java Developer","java developer"],["Frontend Developer","front[ -]?end (?:developer|engineer)"],["Backend Developer","back[ -]?end (?:developer|engineer)"],["Full Stack Developer","full[ -]?stack (?:developer|engineer)"],["QA Engineer","qa engineer|quality assurance engineer|software test engineer"],["Data Engineer","data engineer"]]


def enrich_matching_profile(profile: dict) -> dict:
    """Use only skills found in the user's private PDF, never guess screening answers."""
    resume = get_resume(str(profile["user_id"]))
    if not resume:
        return profile
    try:
        pdf = download_resume(str(resume["storage_path"]))
        if not pdf.startswith(b"%PDF-") or len(pdf) > 6 * 1024 * 1024:
            return profile
        reader = PdfReader(BytesIO(pdf))
        text = " ".join((page.extract_text() or "") for page in reader.pages[:20])
        if not text.strip():
            return profile
        def found(rules):
            return [label for label, pattern in rules if re.search(
                r"(?:^|[^a-z0-9])(?:" + pattern + r")(?=$|[^a-z0-9])", text, re.I)]
        skills = found(SKILL_RULES)
        roles = found(ROLE_RULES)
        existing = _list(profile.get("target_roles"))
        generic = not existing or all(re.fullmatch(r"software engineer(?:ing)?|software developer|it professional", role, re.I) for role in existing)
        cloud_skills = {"AWS", "Azure", "GCP", "Jenkins", "OpenShift", "Docker", "Kubernetes", "Terraform", "CI/CD"}
        if generic and len(cloud_skills.intersection(skills)) >= 4 and not any(re.search(r"devops|site reliability|cloud|platform|infrastructure", role, re.I) for role in roles):
            roles.append("DevOps Engineer")
        enriched = dict(profile)
        enriched["skills"] = list({s.lower(): s for s in _list(profile.get("skills")) + skills}.values())
        if generic and roles:
            enriched["target_roles"] = roles
        return enriched
    except Exception as exc:
        print("Resume matching enrichment unavailable:", type(exc).__name__)
        return profile


def supported_job(job: dict) -> bool:
    if not job.get("direct_apply") or not job.get("auto_apply_supported"):
        return False
    try:
        parsed = urlparse(str(job.get("url") or ""))
        return parsed.scheme == "https" and parsed.hostname in HOSTS
    except Exception:
        return False


def match_score(job: dict, profile: dict) -> int:
    """Mirror the browser's conservative role/skills/experience scoring."""
    if not supported_job(job):
        return 0

    years = float(profile.get("years_experience") or 0)
    title = _norm(job.get("title"))
    category = _norm(job.get("category"))
    if years < 4 and re.search(
        r"\b(senior|sr|staff|lead|principal|manager|architect|director|head)\b",
        title,
    ):
        return 0

    roles = [_norm(x) for x in _list(profile.get("target_roles"))]
    cloud_terms = {
        "cloud",
        "devops",
        "sre",
        "site reliability",
        "platform",
        "infrastructure",
        "kubernetes",
        "release",
        "build",
    }
    wants_cloud = any(
        any(term in role or role in term for term in cloud_terms) for role in roles
    )

    role_match = False
    if wants_cloud and category == "cloud devops sre":
        role_match = True
    else:
        title_tokens = {x for x in title.split() if len(x) > 2}
        for role in roles:
            if role and (role in title or title in role):
                role_match = True
                break
            role_tokens = {x for x in role.split() if len(x) > 2}
            if role_tokens:
                overlap = len(role_tokens & title_tokens) / len(role_tokens)
                if overlap >= 0.5:
                    role_match = True
                    break
    if not role_match:
        return 0

    required = job.get("experience_min")
    if isinstance(required, (int, float)) and float(required) > years + 0.5:
        return 0

    own_skills = {_norm(x) for x in _list(profile.get("skills"))}
    job_skills = {_norm(x) for x in (job.get("skills") or []) if x}
    if job_skills:
        skill_score = round(35 * len(job_skills & own_skills) / len(job_skills))
    else:
        skill_score = 12

    experience_score = 15
    if isinstance(required, (int, float)) and float(required) > years:
        experience_score = 10

    preferred = [_norm(x) for x in _list(profile.get("preferred_locations"))]
    location = _norm(job.get("location"))
    location_score = 5 if (
        not preferred
        or any(x == "india" or x in location for x in preferred)
    ) else 0

    return min(100, 45 + skill_score + experience_score + location_score)


def attempts_created_today(user_id: str) -> set[str]:
    start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    ).isoformat()
    rows = rest_get(
        "application_attempts",
        {
            "user_id": f"eq.{user_id}",
            "created_at": f"gte.{start}",
            "select": "external_job_id",
            "limit": "500",
        },
    )
    return {str(row.get("external_job_id") or "") for row in rows}


def all_attempted_job_ids(user_id: str) -> set[str]:
    rows = rest_get(
        "application_attempts",
        {
            "user_id": f"eq.{user_id}",
            "select": "external_job_id",
            "limit": "5000",
        },
    )
    return {str(row.get("external_job_id") or "") for row in rows}


def queue_new_matches() -> int:
    feed = fetch_public_json(PUBLIC_JOB_FEED_URL)
    jobs = feed.get("jobs") if isinstance(feed.get("jobs"), list) else []

    verification = {}
    try:
        verification = fetch_public_json(VERIFICATION_STATUS_URL).get("jobs") or {}
    except Exception as exc:
        print(f"Verification feed unavailable: {type(exc).__name__}")
        return 0

    profiles = rest_get(
        "candidate_profiles",
        {
            "auto_apply_enabled": "eq.true",
            "consent_version": f"eq.{CONSENT_VERSION}",
            "select": "*",
            "limit": "500",
        },
    )

    queued_total = 0
    for profile in profiles:
        user_id = str(profile.get("user_id") or "")
        if not user_id:
            continue
        daily_limit = max(1, min(int(profile.get("daily_application_limit") or 10), 100))
        today_ids = attempts_created_today(user_id)
        remaining = max(0, daily_limit - len(today_ids))
        if remaining == 0:
            continue

        attempted_ids = all_attempted_job_ids(user_id)
        threshold = max(50, min(int(profile.get("minimum_match_score") or 80), 100))
        matching_profile = enrich_matching_profile(profile)
        ranked = []
        for job in jobs:
            job_id = str(job.get("id") or "")
            if not job_id or job_id in attempted_ids:
                continue
            observed = verification.get(job_id) if isinstance(verification, dict) else None
            if not isinstance(observed, dict) or observed.get("status") != "no_verification_detected":
                continue
            try:
                checked = datetime.fromisoformat(str(observed.get("checked_at_utc") or "").replace("Z", "+00:00"))
                age = (datetime.now(timezone.utc) - checked).total_seconds()
                if not 0 <= age <= 24 * 3600:
                    continue
            except (ValueError, TypeError):
                continue
            score = match_score(job, matching_profile)
            if score >= threshold:
                ranked.append((score, job))

        ranked.sort(key=lambda item: item[0], reverse=True)
        rows = []
        for score, job in ranked[:remaining]:
            rows.append(
                {
                    "user_id": user_id,
                    "external_job_id": str(job.get("id") or ""),
                    "source": str(job.get("source") or ""),
                    "title": str(job.get("title") or ""),
                    "company": str(job.get("company") or ""),
                    "location": str(job.get("location") or ""),
                    "apply_url": str(job.get("url") or ""),
                    "match_score": score,
                    "status": "QUEUED",
                    "message": "Automatically queued from fresh public job feed.",
                }
            )
        if rows:
            rest_insert("application_attempts", rows)
            queued_total += len(rows)

    print(f"Enabled profiles checked: {len(profiles)}")
    print(f"New matching applications queued: {queued_total}")
    return queued_total


def get_profile(user_id: str) -> dict | None:
    rows = rest_get(
        "candidate_profiles",
        {"user_id": f"eq.{user_id}", "select": "*", "limit": "1"},
    )
    return rows[0] if rows else None


def get_screening_answers(user_id: str) -> dict:
    rows = rest_get(
        "screening_answers",
        {"user_id": f"eq.{user_id}", "select": "question,answer"},
    )
    answers = {}
    for row in rows:
        question = str(row.get("question") or "").strip()
        if question:
            answers[question] = row.get("answer")
    return answers


def get_resume(user_id: str) -> dict | None:
    rows = rest_get(
        "resume_variants",
        {
            "user_id": f"eq.{user_id}",
            "active": "eq.true",
            "select": "*",
            "order": "updated_at.desc",
            "limit": "1",
        },
    )
    return rows[0] if rows else None


def download_resume(storage_path: str) -> bytes:
    safe_path = quote(storage_path, safe="/")
    response = requests.get(
        f"{base_url()}/storage/v1/object/authenticated/resumes/{safe_path}",
        headers=headers(),
        timeout=30,
    )
    response.raise_for_status()
    return response.content


def public_status(portal_status: str) -> str:
    if portal_status == "portal_confirmed":
        return "SUBMITTED"
    if portal_status.startswith("portal_uncertain"):
        return "UNCERTAIN"
    if "human_verification" in portal_status:
        return "HUMAN_VERIFICATION_REQUIRED"
    if "missing_screening" in portal_status or "unanswered" in portal_status:
        return "QUESTION_REQUIRED"
    if portal_status == "portal_review_contact":
        return "PROFILE_REQUIRED"
    if "unsupported" in portal_status:
        return "UNSUPPORTED"
    return "REVIEW_REQUIRED"


def process_attempt(attempt: dict) -> None:
    attempt_id = int(attempt["id"])
    user_id = str(attempt["user_id"])

    claimed = patch_attempt(
        attempt_id,
        "QUEUED",
        {"status": "SUBMITTING", "updated_at": datetime.now(timezone.utc).isoformat()},
    )
    if not claimed:
        return

    try:
        profile = get_profile(user_id)
        if not profile:
            patch_attempt(
                attempt_id,
                "SUBMITTING",
                {"status": "PROFILE_REQUIRED", "message": "Candidate profile is missing."},
            )
            return
        if (
            not profile.get("auto_apply_enabled")
            or profile.get("consent_version") != CONSENT_VERSION
        ):
            patch_attempt(
                attempt_id,
                "SUBMITTING",
                {
                    "status": "PAUSED",
                    "message": "Auto Apply is not enabled with current consent.",
                },
            )
            return

        resume = get_resume(user_id)
        if not resume:
            patch_attempt(
                attempt_id,
                "SUBMITTING",
                {"status": "PROFILE_REQUIRED", "message": "No active resume is available."},
            )
            return

        pdf = download_resume(str(resume["storage_path"]))
        if not pdf.startswith(b"%PDF-"):
            patch_attempt(
                attempt_id,
                "SUBMITTING",
                {
                    "status": "REVIEW_REQUIRED",
                    "message": "Stored resume is not a valid PDF.",
                },
            )
            return

        candidate = enrich_matching_profile(profile)
        candidate["screening_answers"] = get_screening_answers(user_id)
        candidate["target_roles"] = ", ".join(_list(candidate.get("target_roles")))
        candidate["skills"] = ", ".join(_list(candidate.get("skills")))
        candidate["preferred_locations"] = ", ".join(
            _list(profile.get("preferred_locations"))
        )

        diagnostic = {}
        job = {
            "id": str(attempt.get("external_job_id") or ""),
            "source": str(attempt.get("source") or ""),
            "title": str(attempt.get("title") or ""),
            "company": str(attempt.get("company") or ""),
            "location": str(attempt.get("location") or ""),
            "url": str(attempt.get("apply_url") or ""),
            "apply_url": str(attempt.get("apply_url") or ""),
        }
        from email_verification import wait_for_user_code
        def provide_code(page, still_valid):
            def authorized():
                latest=get_profile(user_id)
                return bool(latest and latest.get("auto_apply_enabled") and latest.get("consent_version")==CONSENT_VERSION and still_valid())
            return wait_for_user_code(page, attempt_id, user_id, (headers,base_url,rest_get,rest_insert), authorized)
        portal_status = portal_apply(job, candidate, pdf, diagnostic, email_code_provider=provide_code)
        status = public_status(portal_status)
        # Never publish input values, screenshots, employer HTML, or question content in public logs.
        print("Attempt diagnostics:", json.dumps({"attempt": attempt_id, "stage": diagnostic.get("stage"), "result": portal_status, "location": diagnostic.get("location_trace", {}), "validation": diagnostic.get("validation_details", []), "validation_step": diagnostic.get("validation_step"), "resume_attachment": diagnostic.get("resume_attachment"), "exception_type": diagnostic.get("exception_type"), "submit_clicked": diagnostic.get("submit_clicked", False), "post_click_response_count": diagnostic.get("post_click_response_count"), "email_verification": {k: diagnostic[k] for k in ("email_verification_required","email_code_received","email_code_typed","email_code_value_matches","email_code_input_valid","email_verify_button_enabled","email_verify_clicked","email_code_outcome") if k in diagnostic}}, sort_keys=True))
        confirmation = str(diagnostic.get("confirmation") or "")
        message = portal_status
        if status == "QUESTION_REQUIRED":
            missing = [
                str(item).strip()[:160]
                for item in (diagnostic.get("missing_fields") or [])
                if str(item).strip()
            ]
            message = "Required information needed"
            if missing:
                message += ": " + "; ".join(missing[:4])
        elif status == "HUMAN_VERIFICATION_REQUIRED":
            message = "Human verification is required on the employer application page."
        elif status == "PROFILE_REQUIRED":
            message = "Candidate profile needs additional required contact information."
        elif "validation" in portal_status:
            categories = sorted({item["category"] for item in diagnostic.get("validation_details", []) if item.get("category") in {"phone","country","email","linkedin","resume","first_name","last_name","website","other"}})
            message = ("Submission outcome uncertain; do not retry without checking employer receipt." if status == "UNCERTAIN" else "Form validation failed before submission.")
            if categories: message += " Fields: " + ", ".join(categories)
        elif "email_verification" in portal_status or "email_code" in portal_status:
            message = "Employer email verification not confirmed; do not retry automatically. Check the application receipt."
        elif status == "SUBMITTED":
            message = "Application submission confirmed by the employer ATS."
        elif portal_status == "portal_review_location_autocomplete":
            reason = diagnostic.get("location_trace", {}).get("result")
            message = ("Employer location dropdown returned no visible suggestions; manual action required." if reason == "no_visible_options" else "Employer location selection could not be verified; manual action required.")

        patch_attempt(
            attempt_id,
            "SUBMITTING",
            {
                "status": status,
                "message": message[:500],
                "confirmation": confirmation[:200],
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Attempt {attempt_id}: {status}")
    except Exception as exc:
        patch_attempt(
            attempt_id,
            "SUBMITTING",
            {
                "status": "UNCERTAIN",
                "message": f"worker_error:{type(exc).__name__}",
                "updated_at": datetime.now(timezone.utc).isoformat(),
            },
        )
        print(f"Attempt {attempt_id}: UNCERTAIN ({type(exc).__name__})")


def retry_answered_attempts() -> None:
    """Retry only pre-submission missing-question stops after fresh exact answers."""
    rows = rest_get("application_attempts", {
        "status": "eq.QUESTION_REQUIRED",
        "select": "id,user_id,message,updated_at",
        "order": "updated_at.asc",
        "limit": "100",
    })
    for attempt in rows:
        msg = str(attempt.get("message") or "")
        prefix = "Required information needed: "
        if not msg.startswith(prefix) or "select an unambiguous autocomplete suggestion" in msg:
            continue
        questions = [normalize(q) for q in msg[len(prefix):].split("; ") if normalize(q)]
        if not questions:
            continue
        profile = get_profile(str(attempt["user_id"]))
        if not profile or not profile.get("auto_apply_enabled") or profile.get("consent_version") != CONSENT_VERSION:
            continue
        saved = rest_get("screening_answers", {"user_id": f"eq.{attempt['user_id']}", "select": "question,answer,updated_at"})
        valid = {normalize(r["question"]): r for r in saved if isinstance(r.get("answer"), (str, int, float, bool)) and str(r["answer"]).strip()}
        if not all(q in valid for q in questions):
            continue
        def stamp(value):
            return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if not any(stamp(valid[q]["updated_at"]) > stamp(attempt["updated_at"]) for q in questions):
            continue
        patch_attempt(int(attempt["id"]), "QUESTION_REQUIRED", {"status": "QUEUED", "message": "Retry queued after candidate supplied screening answers.", "updated_at": datetime.now(timezone.utc).isoformat()})


def main() -> None:
    if not configured():
        print("Supabase worker not configured; skipping.")
        return

    ensure_resume_bucket()
    retry_answered_attempts()
    queue_new_matches()

    queued = rest_get(
        "application_attempts",
        {
            "status": "eq.QUEUED",
            "select": "id,user_id,external_job_id,source,title,company,location,apply_url,match_score,status",
            "order": "created_at.asc",
            "limit": str(MAX_SUBMISSIONS_PER_RUN),
        },
    )
    print(f"Queued applications selected for submission: {len(queued)}")
    for attempt in queued:
        process_attempt(attempt)


if __name__ == "__main__":
    main()
