from __future__ import annotations

from typing import Any

from sqlalchemy.orm import Session

from app.models import Application, ApplicationArtifact, CandidateProfile, CandidateResume
from app.services.application_generator import generate_application
from app.services.matcher import score_job


class ExternalJob:
    def __init__(self, raw: dict[str, Any]):
        self.id = str(raw.get("id", ""))
        self.title = str(raw.get("title", ""))
        self.company = raw.get("company", {})
        self.location = raw.get("location", {})
        self.description = str(raw.get("description", ""))
        self.url = str(raw.get("redirect_url", "") or raw.get("url", ""))


def company_name(value: Any) -> str:
    if isinstance(value, dict):
        return str(value.get("display_name") or "")
    return str(value or "")


def location_name(value: Any) -> str:
    if isinstance(value, dict):
        area = value.get("area") or []
        return str(value.get("display_name") or " ".join(area))
    return str(value or "")


def build_application(job: ExternalJob, match: dict[str, Any]) -> Application:
    return Application(
        external_job_id=job.id,
        title=job.title,
        company=company_name(job.company),
        location=location_name(job.location),
        apply_url=job.url,
        match_score=float(match.get("score", 0)),
        decision=str(match.get("decision", "REVIEW")),
        status="QUEUED",
        notes="Automatically selected using the configured candidate matching rules.",
    )


def queue_and_prepare(
    db: Session,
    profile: CandidateProfile,
    resume: CandidateResume,
    raw_jobs: list[dict[str, Any]],
    min_score: int,
    limit: int,
    generate_packages: bool = True,
) -> dict[str, Any]:
    prepared: list[dict[str, Any]] = []
    skipped = 0

    for raw in raw_jobs:
        if len(prepared) >= limit:
            break

        job = ExternalJob(raw)
        if not job.id or not job.url:
            skipped += 1
            continue

        match = score_job(job, profile)
        if match["score"] < min_score:
            skipped += 1
            continue

        # Never create duplicate application records for the same external job.
        existing = (
            db.query(Application)
            .filter(Application.external_job_id == job.id)
            .first()
        )
        if existing:
            skipped += 1
            continue

        application = build_application(job, match)
        db.add(application)
        db.flush()

        package = None
        if generate_packages:
            package = generate_application(job, profile, resume.resume_text)
            artifact = ApplicationArtifact(
                application_id=application.id,
                tailored_resume=package.get("tailored_resume", package.get("summary", "")),
                cover_letter=package.get("cover_letter", ""),
            )
            db.add(artifact)
            application.status = "READY_FOR_REVIEW"
            application.notes = (
                "Application package generated. Explicit review/approval is required "
                "before any external submission."
            )

        prepared.append(
            {
                "application_id": application.id,
                "external_job_id": job.id,
                "title": job.title,
                "company": company_name(job.company),
                "location": location_name(job.location),
                "match_score": match["score"],
                "decision": match["decision"],
                "matched_skills": match.get("matched_skills", []),
                "missing_skills": match.get("missing_skills", []),
                "apply_url": job.url,
                "status": application.status,
                "package_generated": package is not None,
            }
        )

    db.commit()

    return {
        "searched": len(raw_jobs),
        "prepared": len(prepared),
        "skipped": skipped,
        "applications": prepared,
    }
