from app.services.matcher import score_job

from fastapi import FastAPI, Depends
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.orm import Session
from pydantic import BaseModel

from app.services.ai_matcher import analyze_job
from app.services.job_sources.adzuna import search_jobs

from app.database import Base, engine, get_db
from app.models import CandidateProfile, Job


# =========================
# DATABASE
# =========================

Base.metadata.create_all(bind=engine)


# =========================
# FASTAPI APP
# =========================

app = FastAPI(
    title="DevOps Job AI",
    version="0.1.0"
)


# =========================
# CORS
# =========================

app.add_middleware(
    CORSMiddleware,
    allow_origins=[
        "http://50.17.126.62:8080",
    ],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


# =========================
# HEALTH
# =========================

@app.get("/health")
def health():
    return {
        "status": "ok",
        "message": "DevOps Job AI is running"
    }


# =========================
# CANDIDATE PROFILE
# =========================

@app.post("/profile")
def create_profile(
    name: str,
    years_experience: float,
    target_roles: str,
    skills: str,
    preferred_locations: str,
    db: Session = Depends(get_db)
):
    profile = CandidateProfile(
        name=name,
        years_experience=years_experience,
        target_roles=target_roles,
        skills=skills,
        preferred_locations=preferred_locations
    )

    db.add(profile)
    db.commit()
    db.refresh(profile)

    return profile


@app.get("/profile")
def get_profile(
    db: Session = Depends(get_db)
):
    profile = db.query(
        CandidateProfile
    ).first()

    return profile


# =========================
# LOCAL DATABASE JOBS
# =========================

@app.post("/jobs")
def create_job(
    title: str,
    company: str,
    location: str,
    description: str,
    url: str = "",
    db: Session = Depends(get_db)
):
    job = Job(
        title=title,
        company=company,
        location=location,
        description=description,
        url=url
    )

    db.add(job)
    db.commit()
    db.refresh(job)

    return job


@app.get("/jobs")
def get_jobs(
    db: Session = Depends(get_db)
):
    jobs = db.query(Job).all()

    return jobs


# =========================
# LOCAL DATABASE JOB MATCHES
# =========================

@app.get("/jobs/matches")
def get_job_matches(
    db: Session = Depends(get_db)
):
    profile = db.query(
        CandidateProfile
    ).first()

    if not profile:
        return {
            "error": "Candidate profile not found"
        }

    jobs = db.query(Job).all()

    results = []

    for job in jobs:

        match = score_job(
            job,
            profile
        )

        results.append({
            "job_id": job.id,
            "title": job.title,
            "company": job.company,
            "location": job.location,
            "url": job.url,

            **match
        })

    results.sort(
        key=lambda x: x["score"],
        reverse=True
    )

    return results


# =========================
# LOCAL DATABASE AI MATCH
# =========================

@app.get("/jobs/{job_id}/ai-match")
def get_ai_match(
    job_id: int,
    db: Session = Depends(get_db)
):
    profile = db.query(
        CandidateProfile
    ).first()

    if not profile:
        return {
            "error": "Candidate profile not found"
        }

    job = db.query(
        Job
    ).filter(
        Job.id == job_id
    ).first()

    if not job:
        return {
            "error": "Job not found"
        }

    result = analyze_job(
        job,
        profile
    )

    return {
        "job_id": job.id,
        "title": job.title,
        "company": job.company,
        "ai_analysis": result
    }


# =========================
# EXTERNAL JOB MODEL
# =========================

class ExternalJob(BaseModel):
    job_id: str
    title: str
    company: str
    location: str
    description: str = ""
    url: str = ""


# =========================
# AI MATCH FOR ADZUNA JOBS
# =========================

@app.post("/jobs/ai-match")
def analyze_external_job(
    job: ExternalJob,
    db: Session = Depends(get_db)
):
    # Get candidate profile
    profile = db.query(
        CandidateProfile
    ).first()

    if not profile:
        return {
            "error": "Candidate profile not found"
        }

    # Create a temporary job object.
    # We do NOT save the Adzuna job to the database.
    class JobData:
        pass

    job_data = JobData()

    job_data.id = job.job_id
    job_data.title = job.title
    job_data.company = job.company
    job_data.location = job.location
    job_data.description = job.description
    job_data.url = job.url

    # Send the external job + candidate profile to AI
    result = analyze_job(
        job_data,
        profile
    )

    return {
        "job_id": job.job_id,
        "title": job.title,
        "company": job.company,
        "location": job.location,
        "url": job.url,
        "ai_analysis": result
    }


# =========================
# REAL JOB SEARCH - ADZUNA
# =========================

@app.get("/jobs/search")
def search_real_jobs(
    keyword: str = "DevOps",
    location: str = "Hyderabad"
):
    result = search_jobs(
        keyword=keyword,
        location=location
    )

    return {
        "count": result.get("count", 0),
        "jobs": result.get("results", [])
    }
