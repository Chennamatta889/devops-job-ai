import json

from app.services.ai_matcher import client


def _parse_json(text: str) -> dict:
    text = (text or "").strip()
    if text.startswith("```"):
        text = text.replace("```json", "").replace("```", "").strip()
    return json.loads(text)


def generate_application(job, profile, resume_text):
    prompt = f"""
You are preparing a truthful, ATS-friendly application package for a DevOps engineer.

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

Rules:
- Use ONLY facts supported by the candidate resume/profile.
- Never invent employers, dates, certifications, skills, projects, metrics, responsibilities, or technologies.
- Tailor wording to the job, but preserve factual accuracy.
- Prefer the candidate's actual quantified achievements when relevant.
- Make the resume ATS-friendly and concise.
- The cover letter must be specific to the role/company and must not claim unsupported experience.

Return ONLY valid JSON with exactly this structure:
{{
  "summary": "tailored professional summary",
  "key_skills": ["skill 1", "skill 2"],
  "tailored_resume": "a complete concise ATS-ready resume using only supported candidate facts",
  "cover_letter": "professional cover letter",
  "resume_changes": ["specific change 1", "specific change 2"]
}}
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
    )
    result = _parse_json(response.text)

    required = ["summary", "key_skills", "tailored_resume", "cover_letter", "resume_changes"]
    for key in required:
        result.setdefault(key, [] if key in {"key_skills", "resume_changes"} else "")

    return result
