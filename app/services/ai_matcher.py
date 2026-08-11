import json
import os

from dotenv import load_dotenv
from google import genai

load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

if not GEMINI_API_KEY:
    raise RuntimeError(
        "GEMINI_API_KEY is not configured."
    )

client = genai.Client(
    api_key=GEMINI_API_KEY
)


def analyze_job(job, profile):

    prompt = f"""
You are an expert technical recruiter specializing
in DevOps and Cloud engineering.

Analyze whether this job is a good match for the
candidate.

CANDIDATE

Name:
{profile.name}

Experience:
{profile.years_experience} years

Target roles:
{profile.target_roles}

Skills:
{profile.skills}

Preferred locations:
{profile.preferred_locations}


JOB

Title:
{job.title}

Company:
{job.company}

Location:
{job.location}

Description:
{job.description}


Return ONLY valid JSON.

Use this exact structure:

{{
    "score": 0,
    "decision": "APPLY",
    "required_skills": [],
    "matched_skills": [],
    "missing_skills": [],
    "nice_to_have_skills": [],
    "experience_required": null,
    "experience_match": true,
    "reason": ""
}}

Rules:

1. score must be between 0 and 100.

2. decision must be one of:
   APPLY
   REVIEW
   SKIP

3. Never invent candidate experience.

4. Separate mandatory requirements from
   preferred/nice-to-have requirements.

5. If the candidate does not have a skill,
   put it in missing_skills.

6. Consider role, experience, skills and location.

7. A missing nice-to-have skill should not
   heavily reduce the score.

8. If the job clearly requires significantly
   more experience than the candidate has,
   reduce the score.

9. Return ONLY JSON.
"""

    response = client.models.generate_content(
        model="gemini-3.5-flash-lite",
        contents=prompt,
    )

    text = response.text.strip()

    # Remove markdown fences if the model adds them
    if text.startswith("```"):
        text = text.replace("```json", "")
        text = text.replace("```", "")
        text = text.strip()

    return json.loads(text)
