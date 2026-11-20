"""Process queued DraftflowAI applications from Supabase.

Uses the service-role key only inside the private GitHub Actions runner.
Never prints candidate profile values, resume contents, tokens, or storage URLs.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from urllib.parse import quote

import requests

from portal import portal_apply

CONSENT_VERSION = "2026-11-v1"
MAX_PER_RUN = 5


def configured() -> bool:
    return bool(os.getenv("SUPABASE_URL", "").strip() and os.getenv("SUPABASE_SERVICE_ROLE_KEY", "").strip())


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
    if "human_verification" in portal_status:
        return "HUMAN_VERIFICATION_REQUIRED"
    if "missing_screening" in portal_status or "unanswered" in portal_status:
        return "QUESTION_REQUIRED"
    if portal_status == "portal_review_contact":
        return "PROFILE_REQUIRED"
    if "unsupported" in portal_status:
        return "UNSUPPORTED"
    if portal_status.startswith("portal_uncertain"):
        return "UNCERTAIN"
    return "REVIEW_REQUIRED"


def process_attempt(attempt: dict) -> None:
    attempt_id = int(attempt["id"])
    user_id = str(attempt["user_id"])

    # Atomic claim prevents a second worker from taking the same queued row.
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
            patch_attempt(attempt_id, "SUBMITTING", {"status": "PROFILE_REQUIRED", "message": "Candidate profile is missing."})
            return
        if not profile.get("auto_apply_enabled") or profile.get("consent_version") != CONSENT_VERSION:
            patch_attempt(attempt_id, "SUBMITTING", {"status": "PAUSED", "message": "Auto Apply is not enabled with current consent."})
            return

        resume = get_resume(user_id)
        if not resume:
            patch_attempt(attempt_id, "SUBMITTING", {"status": "PROFILE_REQUIRED", "message": "No active resume is available."})
            return

        pdf = download_resume(str(resume["storage_path"]))
        if not pdf.startswith(b"%PDF-"):
            patch_attempt(attempt_id, "SUBMITTING", {"status": "REVIEW_REQUIRED", "message": "Stored resume is not a valid PDF."})
            return

        candidate = dict(profile)
        candidate["screening_answers"] = get_screening_answers(user_id)
        candidate["target_roles"] = ", ".join(profile.get("target_roles") or [])
        candidate["skills"] = ", ".join(profile.get("skills") or [])
        candidate["preferred_locations"] = ", ".join(profile.get("preferred_locations") or [])

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
        portal_status = portal_apply(job, candidate, pdf, diagnostic)
        status = public_status(portal_status)
        message = portal_status
        confirmation = str(diagnostic.get("confirmation") or "")

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


def main() -> None:
    if not configured():
        print("Supabase worker not configured; skipping.")
        return

    queued = rest_get(
        "application_attempts",
        {
            "status": "eq.QUEUED",
            "select": "id,user_id,external_job_id,source,title,company,location,apply_url,match_score,status",
            "order": "created_at.asc",
            "limit": str(MAX_PER_RUN),
        },
    )
    print(f"Queued applications selected: {len(queued)}")
    for attempt in queued:
        process_attempt(attempt)


if __name__ == "__main__":
    main()
