from typing import Any

from fastapi import Depends, FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.database import Base, engine, get_db
from app.models import Application, CandidateProfile, Job
from app.services.ai_matcher import analyze_job
from app.services.job_sources.adzuna import search_jobs
from app.services.matcher import score_job

Base.metadata.create_all(bind=engine)

app = FastAPI(title="DevOps Job AI", version="0.2.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://50.17.126.62:8080"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


@app.get("/health")
def health():
    return {"status": "ok", "message": "DevOps Job AI is running"}


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
        self.url = str(raw.get("redirect_url", ""))


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


class ExternalJob(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    description: str = ""
    url: str = ""


@app.post("/jobs/ai-match")
def analyze_external_job(job: ExternalJob, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found")

    class JobData:
        pass

    job_data = JobData()
    job_data.id = job.job_id
    job_data.title = job.title
    job_data.company = job.company
    job_data.location = job.location
    job_data.description = job.description
    job_data.url = job.url

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


@app.post("/applications/queue-recommended")
def queue_recommended_applications(keyword: str = "DevOps", location: str = "Hyderabad", min_score: int = 85, limit: int = 10, db: Session = Depends(get_db)):
    profile = db.query(CandidateProfile).first()
    if not profile:
        raise HTTPException(status_code=400, detail="Candidate profile not found. Create /profile first.")

    result = search_jobs(keyword=keyword, location=location)
    queued = []

    for raw in result.get("results", []):
        if len(queued) >= limit:
            break

        job = ExternalJobData(raw)
        match = score_job(job, profile)
        if match["score"] < min_score or not job.url:
            continue

        existing = db.query(Application).filter(Application.external_job_id == job.id).first()
        if existing:
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
            notes="Automatically selected from the recommended-job queue.",
        )
        db.add(application)
        queued.append({
            "job_id": job.id,
            "title": job.title,
            "company": match["company"],
            "match_score": match["score"],
            "apply_url": job.url,
        })

    db.commit()
    return {"queued": len(queued), "applications": queued}


@app.get("/applications")
def list_applications(db: Session = Depends(get_db)):
    return db.query(Application).order_by(Application.match_score.desc()).all()


@app.get("/applications/{application_id}")
def get_application(application_id: int, db: Session = Depends(get_db)):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    return application


@app.post("/applications/{application_id}/mark-applied")
def mark_application_applied(application_id: int, db: Session = Depends(get_db)):
    application = db.query(Application).filter(Application.id == application_id).first()
    if not application:
        raise HTTPException(status_code=404, detail="Application not found")
    application.status = "APPLIED"
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
