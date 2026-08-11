from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel, Field
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Application, ApplicationArtifact, CandidateProfile, CandidateResume, Job
from app.services.ai_matcher import analyze_job
from app.services.application_generator import generate_application
from app.services.application_pipeline import ExternalJob, queue_and_prepare
from app.services.job_sources.adzuna import search_jobs
from app.services.matcher import score_job

Base.metadata.create_all(bind=engine)

app = FastAPI(title="DevOps Job AI", version="0.4.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://50.17.126.62:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "message": "DevOps Job AI is running", "version": "0.4.0"}


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

    result = search_jobs(keyword=keyword, location=location)
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
    return {"job_id": job.job_id, "title": job.title, "company": job.company, "location": job.location, "url": job.url, "ai_analysis": analyze_job(job_data, profile)}


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
    min_score: int = Field(default=85, ge=0, le=100),
    limit: int = Field(default=10, ge=1, le=50),
    db: Session = Depends(get_db),
):
    """Search, score, deduplicate and generate application packages in one call.

    External job submission is intentionally not performed here. Packages are
    placed in READY_FOR_REVIEW so the candidate can explicitly approve them.
    """
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
    queued = queue_and_prepare(db, profile, None, result.get("results", []), min_score, limit, generate_packages=False) if False else None

    # Preserve the existing endpoint semantics while using the same matcher.
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
    """Explicitly approve an application package for submission.

    This endpoint records the candidate's approval. It does not submit to a
    third-party employer site because those sites use different forms, login,
    CAPTCHA and consent flows that cannot safely be assumed to be equivalent.
    """
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
