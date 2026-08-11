import json

from google import genai

from app.services.ai_matcher import client


def generate_application(job, profile, resume_text):
    prompt = f"""
You are preparing a job application for a DevOps engineer.

CANDIDATE RESUME
{resume_text}

CANDIDATE PROFILE
Name: {profile.name}
Experience: {profile.years_experience} years
Target roles: {profile.target_roles}
Skills: {profile.skills}
Preferred locations: {profile.preferred_locations}

JOB
Title: {job.title}
Company: {job.company}
Location: {job.location}
Description: {job.description}

Create a truthful, ATS-friendly application package.
Do not invent employers, dates, certifications, skills, projects, metrics, or experience.
Use only information present in the resume/profile.

Return ONLY valid JSON with exactly this structure:
{{
  "summary": "short tailored professional summary",
  "key_skills": [],
  "cover_letter": "professional cover letter",
  "resume_changes": []
}}

resume_changes should contain concise suggestions for tailoring the existing resume.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
    )

    text = response.text.strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()

    return json.loads(text)
