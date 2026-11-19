from typing import Any
from datetime import datetime, timedelta
from io import BytesIO
from types import SimpleNamespace
import os
import re
import requests

from fastapi import Depends, FastAPI, File, Form, HTTPException, UploadFile
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Application, ApplicationArtifact, AutoApplyAttempt, AutoApplyProfile, CandidateProfile, CandidateResume, Job, ResumeVariant
from app.services.ai_matcher import analyze_job
from app.services.application_generator import generate_application
from app.services.application_pipeline import ExternalJob, queue_and_prepare
from app.services.application_submitter import auto_submit_supported, submit_application
from app.services.job_sources.adzuna import search_jobs
from app.services.matcher import score_job
from pypdf import PdfReader

Base.metadata.create_all(bind=engine)

app = FastAPI(title="DevOps Job AI", version="0.5.0")

cors_origins=[
    "https://chennamatta889.github.io",
    "http://localhost:5173",
]
extra_origins=[x.strip() for x in os.getenv("CORS_ORIGINS","").split(",") if x.strip()]
cors_origins.extend(extra_origins)

app.add_middleware(
    CORSMiddleware,
    allow_origins=cors_origins,
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "message": "DevOps Job AI is running", "version": "0.5.0"}

AUTO_APPLY_CONSENT_VERSION = "2026-11-v1"
PUBLIC_JOB_FEED_URL = os.getenv(
    "PUBLIC_JOB_FEED_URL",
    "https://raw.githubusercontent.com/Chennamatta889/devops-job-ai/main/data/jobs.json",
)
VERIFICATION_STATUS_URL = os.getenv(
    "VERIFICATION_STATUS_URL",
    "https://raw.githubusercontent.com/Chennamatta889/devops-job-ai/main/data/verification-status.json",
)

def _require_private_auto_apply():
    if os.getenv("AUTO_APPLY_PRIVATE_MODE", "").lower() != "true":
        raise HTTPException(
            status_code=503,
            detail="Auto Apply is disabled until a private authenticated backend is configured.",
        )

def _csv(value: str):
    return [item.strip() for item in str(value or "").split(",") if item.strip()]

def _norm(value: str):
    return re.sub(r"[^a-z0-9+#. ]+", " ", str(value or "").lower()).strip()

def _token_set(value: str):
    return {item for item in _norm(value).split() if len(item) > 1}

def _public_job_match(job: dict, profile: AutoApplyProfile):
    if not job.get("direct_apply") or not auto_submit_supported(str(job.get("url", ""))):
        return 0, "unsupported_ats"

    title = _norm(job.get("title", ""))
    target_roles = _csv(profile.target_roles)
    role_score = 0
    for role in target_roles:
        role_n = _norm(role)
        if role_n and (role_n in title or title in role_n):
            role_score = max(role_score, 45)
            continue
        role_tokens = _token_set(role)
        title_tokens = _token_set(title)
        if role_tokens and title_tokens:
            overlap = len(role_tokens & title_tokens) / len(role_tokens | title_tokens)
            if overlap >= 0.5:
                role_score = max(role_score, round(35 * overlap))
    if role_score == 0:
        return 0, "role"

    own_skills = {_norm(item) for item in _csv(profile.skills)}
    job_skills = {_norm(item) for item in job.get("skills", []) if item}
    if job_skills:
        matched = len(job_skills & own_skills)
        skill_score = round(35 * matched / len(job_skills))
    else:
        skill_score = 12

    required = job.get("experience_min")
    if isinstance(required, (int, float)):
        if float(required) > profile.years_experience + 0.5:
            return 0, "experience"
        experience_score = 15 if float(required) <= profile.years_experience else 10
    else:
        experience_score = 10

    preferred = [_norm(item) for item in _csv(profile.preferred_locations)]
    location = _norm(job.get("location", ""))
    location_score = 5 if not preferred or any(item in location or item == "india" for item in preferred) else 0

    total = min(100, role_score + skill_score + experience_score + location_score)
    return total, "matched"

def _resume_fit(job: dict, resume: ResumeVariant):
    title_tokens = _token_set(job.get("title", ""))
    role_tokens = _token_set(resume.target_roles)
    role_overlap = len(title_tokens & role_tokens)
    job_skills = {_norm(x) for x in job.get("skills", []) if x}
    resume_skills = {_norm(x) for x in _csv(resume.skills)}
    skill_overlap = len(job_skills & resume_skills)
    exp_gap = abs(float(resume.years_experience or 0) - float(job.get("experience_min") or resume.years_experience or 0))
    return (role_overlap * 10) + (skill_overlap * 4) - min(exp_gap, 10)

class AutoApplyProfileRequest(BaseModel):
    name: str
    email: str
    phone: str = ""
    years_experience: float
    target_roles: str
    skills: str
    preferred_locations: str = "India"
    minimum_match_score: int = 80
    daily_application_limit: int = 10

class AutoApplyConsentRequest(BaseModel):
    authorize: bool

@app.post("/auto-apply/profile")
def save_auto_apply_profile(payload: AutoApplyProfileRequest, db: Session = Depends(get_db)):
    _require_private_auto_apply()
    if not 0 <= payload.years_experience <= 50:
        raise HTTPException(status_code=400, detail="years_experience is invalid")
    if not 50 <= payload.minimum_match_score <= 100:
        raise HTTPException(status_code=400, detail="minimum_match_score must be 50-100")
    if not 1 <= payload.daily_application_limit <= 50:
        raise HTTPException(status_code=400, detail="daily_application_limit must be 1-50")
    profile = db.query(AutoApplyProfile).filter(AutoApplyProfile.user_key == "local").first()
    values = payload.model_dump()
    if profile:
        for key, value in values.items():
            setattr(profile, key, value)
    else:
        profile = AutoApplyProfile(user_key="local", **values)
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile

@app.post("/auto-apply/resumes")
async def upload_auto_apply_resume(
    file: UploadFile = File(...),
    target_roles: str = Form(""),
    skills: str = Form(""),
    years_experience: float = Form(0),
    db: Session = Depends(get_db),
):
    _require_private_auto_apply()
    data = await file.read()
    if len(data) > 6 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Resume must be 6 MB or smaller")
    if file.content_type != "application/pdf" or not data.startswith(b"%PDF-"):
        raise HTTPException(status_code=400, detail="Only valid PDF resumes are accepted")
    try:
        reader = PdfReader(BytesIO(data))
        if not reader.pages:
            raise ValueError("empty PDF")
        resume_text = "\n".join((page.extract_text() or "") for page in reader.pages).strip()
    except Exception as exc:
        raise HTTPException(status_code=400, detail=f"Resume PDF could not be read: {type(exc).__name__}")
    if not resume_text:
        raise HTTPException(status_code=400, detail="Resume PDF has no readable text")
    resume = ResumeVariant(
        user_key="local",
        filename=(file.filename or "resume.pdf")[:255],
        content_type="application/pdf",
        pdf_bytes=data,
        resume_text=resume_text,
        target_roles=target_roles,
        skills=skills,
        years_experience=years_experience,
        active=True,
    )
    db.add(resume)
    db.commit()
    db.refresh(resume)
    return {"id": resume.id, "filename": resume.filename, "pages": len(reader.pages), "active": True}

@app.post("/auto-apply/enable")
def enable_auto_apply(payload: AutoApplyConsentRequest, db: Session = Depends(get_db)):
    _require_private_auto_apply()
    if not payload.authorize:
        raise HTTPException(status_code=400, detail="Explicit authorization is required")
    profile = db.query(AutoApplyProfile).filter(AutoApplyProfile.user_key == "local").first()
    resume = db.query(ResumeVariant).filter(
        ResumeVariant.user_key == "local", ResumeVariant.active.is_(True)
    ).first()
    if not profile or not resume:
        raise HTTPException(status_code=400, detail="Save profile and upload at least one active resume first")
    profile.auto_apply_enabled = True
    profile.consent_version = AUTO_APPLY_CONSENT_VERSION
    profile.consented_at = datetime.utcnow()
    db.commit()
    return {"enabled": True, "consent_version": profile.consent_version}

@app.post("/auto-apply/disable")
def disable_auto_apply(db: Session = Depends(get_db)):
    _require_private_auto_apply()
    profile = db.query(AutoApplyProfile).filter(AutoApplyProfile.user_key == "local").first()
    if profile:
        profile.auto_apply_enabled = False
        db.commit()
    return {"enabled": False}

@app.get("/auto-apply/status")
def auto_apply_status(db: Session = Depends(get_db)):
    _require_private_auto_apply()
    profile = db.query(AutoApplyProfile).filter(AutoApplyProfile.user_key == "local").first()
    resumes = db.query(ResumeVariant).filter(ResumeVariant.user_key == "local", ResumeVariant.active.is_(True)).all()
    attempts = db.query(AutoApplyAttempt).filter(AutoApplyAttempt.user_key == "local").order_by(AutoApplyAttempt.created_at.desc()).limit(20).all()
    return {
        "configured": bool(profile and resumes),
        "enabled": bool(profile and profile.auto_apply_enabled),
        "resume_count": len(resumes),
        "profile": profile,
        "recent_attempts": attempts,
    }

@app.post("/auto-apply/run")
def run_auto_apply(db: Session = Depends(get_db)):
    _require_private_auto_apply()
    profile = db.query(AutoApplyProfile).filter(AutoApplyProfile.user_key == "local").first()
    if not profile or not profile.auto_apply_enabled or profile.consent_version != AUTO_APPLY_CONSENT_VERSION:
        raise HTTPException(status_code=400, detail="Auto Apply is not enabled with current consent")
    resumes = db.query(ResumeVariant).filter(ResumeVariant.user_key == "local", ResumeVariant.active.is_(True)).all()
    if not resumes:
        raise HTTPException(status_code=400, detail="No active resume uploaded")

    start = datetime.utcnow().replace(hour=0, minute=0, second=0, microsecond=0)
    used = db.query(AutoApplyAttempt).filter(
        AutoApplyAttempt.user_key == "local",
        AutoApplyAttempt.created_at >= start,
    ).count()
    remaining = max(0, profile.daily_application_limit - used)
    if remaining == 0:
        return {"attempted": 0, "message": "Daily application limit reached", "remaining": 0}

    try:
        response = requests.get(PUBLIC_JOB_FEED_URL, timeout=20)
        response.raise_for_status()
        jobs = response.json().get("jobs", [])
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"Could not load public job feed: {type(exc).__name__}")

    verification_jobs = {}
    try:
        verification_response = requests.get(VERIFICATION_STATUS_URL, timeout=15)
        if verification_response.ok:
            verification_jobs = verification_response.json().get("jobs", {})
    except Exception:
        verification_jobs = {}

    require_no_verification = os.getenv("AUTO_APPLY_REQUIRE_NO_VERIFICATION", "true").lower() != "false"

    ranked = []
    for job in jobs:
        verification = verification_jobs.get(str(job.get("id", "")), {})
        verification_status = str(verification.get("status", "unknown"))
        if require_no_verification and verification_status != "no_verification_detected":
            continue
        score, reason = _public_job_match(job, profile)
        if reason != "matched" or score < profile.minimum_match_score:
            continue
        exists = db.query(AutoApplyAttempt).filter(
            AutoApplyAttempt.user_key == "local",
            AutoApplyAttempt.external_job_id == str(job.get("id", "")),
        ).first()
        if exists:
            continue
        ranked.append((score, job))
    ranked.sort(key=lambda item: item[0], reverse=True)

    results = []
    for score, job in ranked[:remaining]:
        resume = max(resumes, key=lambda item: _resume_fit(job, item))
        attempt = AutoApplyAttempt(
            user_key="local",
            external_job_id=str(job.get("id", "")),
            title=str(job.get("title", "")),
            company=str(job.get("company", "")),
            location=str(job.get("location", "")),
            apply_url=str(job.get("url", "")),
            match_score=score,
            status="SUBMITTING",
            message=f"Using resume: {resume.filename}",
        )
        db.add(attempt)
        db.commit()
        db.refresh(attempt)

        application = SimpleNamespace(apply_url=attempt.apply_url)
        artifact = SimpleNamespace(tailored_resume=resume.resume_text, cover_letter="")
        result = submit_application(application, artifact, profile, resume_pdf_bytes=resume.pdf_bytes)
        attempt.status = result.status
        attempt.message = result.message
        db.commit()
        results.append({
            "job_id": attempt.external_job_id,
            "title": attempt.title,
            "company": attempt.company,
            "score": score,
            "status": attempt.status,
            "message": attempt.message,
        })

    return {"attempted": len(results), "remaining": max(0, remaining - len(results)), "results": results}


class ProfileRequest(BaseModel):
    name: str
    years_experience: float
    target_roles: str
    skills: str
    preferred_locations: str


@app.post("/profile")
def create_or_replace_profile(payload: ProfileRequest, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if profile:
        profile.name = payload.name
        profile.years_experience = payload.years_experience
        profile.target_roles = payload.target_roles
        profile.skills = payload.skills
        profile.preferred_locations = payload.preferred_locations
    else:
        profile = CandidateProfile(**payload.model_dump())
        db.add(profile)
    db.commit()
    db.refresh(profile)
    return profile


@app.get("/profile")
def get_profile(db: Session = Depends(get_db)):
    return db.query(CandidateProfile).first()


class ResumeRequest(BaseModel):
    filename: str = "resume.txt"
    resume_text: str


@app.post("/resume")
def save_resume(payload: ResumeRequest, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Create /profile before saving the resume")

    resume = db.query(CandidateResume).filter(CandidateResume.profile_id == profile.id).first()
    if resume:
        resume.filename = payload.filename
        resume.resume_text = payload.resume_text
    else:
        resume = CandidateResume(profile_id=profile.id, filename=payload.filename, resume_text=payload.resume_text)
        db.add(resume)

    db.commit()
    db.refresh(resume)
    return {"id": resume.id, "filename": resume.filename, "profile_id": resume.profile_id, "message": "Resume saved successfully"}


@app.get("/resume")
def get_resume(db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=404, detail="Candidate profile not found")
    resume = db.query(CandidateResume).filter(CandidateResume.profile_id == profile.id).first()
    if not resume:
        raise HTTPException(status_code=404, detail="Resume not found")
    return resume


@app.post("/jobs")
def create_job(title: str, company: str, location: str, description: str, url: str = "", db: Session = Depends(get_db)):
    job = Job(title=title, company=company, location=location, description=description, url=url)
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


@app.get("/jobs")
def get_jobs(db: Session = Depends(get_db)):
    return db.query(Job).all()


@app.get("/jobs/matches")
def get_job_matches(db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found")
    results = [{"job_id": job.id, **score_job(job, profile)} for job in db.query(Job).all()]
    results.sort(key=lambda item: item["score"], reverse=True)
    return results


class ExternalJobData:
    def __init__(self, raw: dict[str, Any]):
        self.id = str(raw.get("id", ""))
        self.title = str(raw.get("title", ""))
        self.company = raw.get("company", {})
        self.location = raw.get("location", {})
        self.description = str(raw.get("description", ""))
        self.url = str(raw.get("redirect_url", "") or raw.get("url", ""))


@app.get("/jobs/search")
def search_real_jobs(keyword: str = "DevOps", location: str = "Hyderabad"):
    result = search_jobs(keyword=keyword, location=location)
    return {"count": result.get("count", 0), "jobs": result.get("results", [])}


@app.get("/jobs/recommended")
def recommended_jobs(keyword: str = "DevOps", location: str = "Hyderabad", min_score: int = 70, limit: int = 20, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found. Create /profile first.")

    result = search_jobs(keyword=keyword, location=location, results_per_page=min(max(limit * 3, 20), 100))
    raw_jobs = result.get("results", [])
    scored = []
    for raw in raw_jobs:
        job = ExternalJobData(raw)
        match = score_job(job, profile)
        if match["score"] >= min_score:
            scored.append({
                "job_id": job.id,
                "title": job.title,
                "company": match["company"],
                "location": match["location"],
                "description": job.description,
                "apply_url": job.url,
                **match,
            })

    scored.sort(key=lambda item: item["score"], reverse=True)
    return {"searched": len(raw_jobs), "recommended": len(scored[:limit]), "jobs": scored[:limit]}


class ExternalJobRequest(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    description: str = ""
    url: str = ""


@app.post("/jobs/ai-match")
def analyze_external_job(job: ExternalJobRequest, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found")

    job_data = ExternalJob({
        "id": job.job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "description": job.description,
        "url": job.url,
    })
    return {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "ai_analysis": analyze_job(job_data, profile),
    }


class QueueApplicationRequest(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    apply_url: str
    match_score: float = 0
    decision: str = "REVIEW"
    notes: str = ""


@app.post("/applications/queue")
def queue_application(payload: QueueApplicationRequest, db: Session = Depends(get_db)):
    existing = db.query(Application).filter(Application.external_job_id == payload.job_id).first()
    if existing:
        return existing
    application = Application(
        external_job_id=payload.job_id,
        title=payload.title,
        company=payload.company,
        location=payload.location,
        apply_url=payload.apply_url,
        match_score=payload.match_score,
        decision=payload.decision,
        status="QUEUED",
        notes=payload.notes,
    )
    db.add(application)
    db.commit()
    db.refresh(application)
    return application


@app.post("/applications/auto-prepare")
def auto_prepare_applications(
    keyword: str = "DevOps",
    location: str = "Hyderabad",
    min_score: int = 85,
    limit: int = 10,
    db: Session = Depends(get_db),
):
    """Search, score, deduplicate and generate application packages in one call."""
    if not 0 <= min_score <= 100:
        raise HTTPException(status_code=400, detail="min_score must be between 0 and 100")
    if not 1 <= limit <= 50:
        raise HTTPException(status_code=400, detail="limit must be between 1 and 50")

    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found. Create /profile first.")
    resume = db.query(CandidateResume).filter(CandidateResume.profile_id == profile.id).first()
    if not resume:
        raise HTTPException(status_code=400, detail="Resume not found. Save /resume first.")

    result = search_jobs(keyword=keyword, location=location, results_per_page=min(max(limit * 3, 20), 100))
    return queue_and_prepare(
        db=db,
        profile=profile,
        resume=resume,
        raw_jobs=result.get("results", []),
        min_score=min_score,
        limit=limit,
        generate_packages=True,
    )


@app.post("/applications/queue-recommended")
def queue_recommended_applications(keyword: str = "DevOps", location: str = "Hyderabad", min_score: int = 85, limit: int = 10, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found. Create /profile first.")
    result = search_jobs(keyword=keyword, location=location, results_per_page=min(max(limit * 3, 20), 100))
    created = []
    for raw in result.get("results", []):
        if len(created) >= limit:
            break
        job = ExternalJobData(raw)
        match = score_job(job, profile)
        if match["score"] < min_score or not job.url:
            continue
        if db.query(Application).filter(Application.external_job_id == job.id).first():
            continue
        application = Application(
            external_job_id=job.id,
            title=job.title,
            company=match["company"],
            location=match["location"],
            apply_url=job.url,
            match_score=match["score"],
            decision=match["decision"],
            status="QUEUED",
            notes="Queued from recommended jobs. Generate package before review.",
        )
        db.add(application)
        created.append({"job_id": job.id, "title": job.title, "company": match["company"], "match_score": match["score"], "apply_url": job.url})
    db.commit()
    return {"queued": len(created), "applications": created}


@app.post("/applications/{application_id}/generate-package")
def generate_application_package(application_id: int, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found")
    resume = db.query(CandidateResume).filter(CandidateResume.profile_id == profile.id).first()
    if not resume:
        raise HTTPException(status_code=400, detail="Resume not found. Save /resume first.")
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")

    class JobData:
        pass
    job = JobData()
    job.id = application.external_job_id
    job.title = application.title
    job.company = application.company
    job.location = application.location
    job.description = ""
    job.url = application.apply_url

    package = generate_application(job, profile, resume.resume_text)
    artifact = db.query(ApplicationArtifact).filter(ApplicationArtifact.application_id == application.id).first()
    if artifact:
        artifact.tailored_resume = package.get("tailored_resume", package.get("summary", ""))
        artifact.cover_letter = package.get("cover_letter", "")
    else:
        artifact = ApplicationArtifact(
            application_id=application.id,
            tailored_resume=package.get("tailored_resume", package.get("summary", "")),
            cover_letter=package.get("cover_letter", ""),
        )
        db.add(artifact)
    application.status = "READY_FOR_REVIEW"
    application.notes = "Application package generated. Explicit approval is required before external submission."
    db.commit()
    db.refresh(artifact)
    return {"application_id": application.id, "status": application.status, "job": {"title": application.title, "company": application.company, "apply_url": application.apply_url}, "package": package}


@app.get("/applications")
def list_applications(db: Session = Depends(get_db)):
    return db.query(Application).order_by(Application.match_score.desc()).all()


@app.get("/applications/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db)):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.get("/applications/{application_id}/package")
def get_application_package(application_id: int, db: Session = Depends(get_db)):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    artifact = db.query(ApplicationArtifact).filter(ApplicationArtifact.application_id == application.id).first()
    if not artifact:
        raise HTTPException(status_code=404, detail="Application package not generated")
    return artifact


@app.post("/applications/{application_id}/approve")
def approve_application(application_id: int, db: Session = Depends(get_db)):
    """Record explicit candidate approval before external submission."""
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status != "READY_FOR_REVIEW":
        raise HTTPException(status_code=400, detail=f"Application must be READY_FOR_REVIEW, current status is {application.status}")
    application.status = "APPROVED"
    application.notes = "Candidate approved the application package for submission."
    db.commit()
    db.refresh(application)
    return application


@app.post("/applications/{application_id}/submit")
def submit_approved_application(application_id: int, db: Session = Depends(get_db)):
    """Attempt browser submission for an explicitly approved application.

    The worker does not bypass CAPTCHA, MFA, login walls, or bot protections.
    Those cases become MANUAL_ACTION_REQUIRED instead of being reported as applied.
    """
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status != "APPROVED":
        raise HTTPException(status_code=400, detail=f"Application must be APPROVED before submission, current status is {application.status}")

    artifact = db.query(ApplicationArtifact).filter(ApplicationArtifact.application_id == application.id).first()
    if not artifact:
        raise HTTPException(status_code=400, detail="Application package not generated")

    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found")

    result = submit_application(application, artifact, profile)
    application.status = result.status
    application.notes = result.message + (f" Final URL: {result.final_url}" if result.final_url else "")
    db.commit()
    db.refresh(application)

    return {
        "application_id": application.id,
        "status": application.status,
        "submitted": result.submitted,
        "message": result.message,
        "final_url": result.final_url,
    }


@app.post("/applications/{application_id}/mark-applied")
def mark_application_applied(application_id: int, db: Session = Depends(get_db)):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    if application.status not in {"APPROVED", "READY_FOR_REVIEW"}:
        raise HTTPException(status_code=400, detail="Application must be approved or ready for review")
    application.status = "APPLIED"
    application.notes = "Application marked as submitted by the candidate."
    db.commit()
    db.refresh(application)
    return application


@app.post("/applications/{application_id}/mark-failed")
def mark_application_failed(application_id: int, notes: str = "", db: Session = Depends(get_db)):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    application.status = "FAILED"
    application.notes = notes
    db.commit()
    db.refresh(application)
    return application
