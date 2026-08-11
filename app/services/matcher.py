import re
from typing import Any

from app.models import CandidateProfile

KNOWN_DEVOPS_SKILLS = [
    "AWS", "Azure", "GCP", "Kubernetes", "Docker", "Terraform", "Jenkins",
    "Azure DevOps", "GitHub Actions", "GitLab CI", "Harness", "OpenShift",
    "Linux", "Bash", "PowerShell", "Python", "Helm", "Ansible", "ArgoCD",
    "Prometheus", "Grafana", "Istio", "Vault", "Packer", "CloudFormation",
    "EKS", "AKS", "GKE", "Snyk", "Aqua Security", "GitLeaks", "CloudWatch",
    "Splunk", "Dynatrace", "IAM", "ACR", "VPC", "EC2", "RDS", "S3",
    "CI/CD", "DevSecOps", "Infrastructure as Code", "REST API", "REST APIs",
]

PRIMARY_ROLE_TERMS = [
    "devops", "dev sec ops", "devsecops", "cloud engineer", "cloud devops",
    "platform engineer", "platform devops", "site reliability", "sre",
    "release engineer", "build engineer", "build release", "infrastructure engineer",
    "cloud infrastructure", "production engineer", "systems engineer",
]

SECONDARY_ROLE_TERMS = [
    "cloud operations", "platform operations", "infrastructure automation",
    "reliability engineer", "automation engineer",
]

NON_DEVOPS_ROLE_TERMS = [
    "software developer", "application developer", "frontend", "backend developer",
    "full stack", "data scientist", "data engineer", "gis developer", "gis",
    "technical project manager", "project manager", "sales", "inside sales",
    "security consultant", "cyber security consultant", "qa engineer", "test manager",
]


def normalize(text: str) -> str:
    return re.sub(r"[^a-z0-9+#.\-/ ]+", " ", str(text or "").lower())


def contains_term(text: str, term: str) -> bool:
    text_n = normalize(text)
    term_n = normalize(term).strip()
    if not term_n:
        return False
    pattern = r"(?<![a-z0-9+#.\-/])" + re.escape(term_n) + r"(?![a-z0-9+#.\-/])"
    return re.search(pattern, text_n) is not None


def get_list(value: str | None) -> list[str]:
    return [item.strip() for item in str(value or "").split(",") if item.strip()]


def extract_required_years(text: str) -> float | None:
    text = str(text or "").lower()
    patterns = [
        r"(\d+(?:\.\d+)?)\s*\+\s*(?:years|yrs)",
        r"(\d+(?:\.\d+)?)\s*(?:years|yrs)\s*(?:of)?\s*experience",
        r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:years|yrs)",
    ]
    for pattern in patterns:
        match = re.search(pattern, text)
        if match:
            return float(match.group(1))
    return None


def _job_location(job: Any) -> str:
    location = getattr(job, "location", "")
    if isinstance(location, dict):
        area = location.get("area", []) or []
        return str(location.get("display_name") or " ".join(area))
    return str(location or "")


def _job_company(job: Any) -> str:
    company = getattr(job, "company", "")
    if isinstance(company, dict):
        return str(company.get("display_name") or "")
    return str(company or "")


def _job_url(job: Any) -> str:
    return str(getattr(job, "url", "") or getattr(job, "redirect_url", "") or "")


def _skill_matches(required_skill: str, candidate_skills: list[str]) -> bool:
    """Match skill phrases in either direction, including variants such as CI/CD Pipelines."""
    required = normalize(required_skill).strip()
    for candidate in candidate_skills:
        candidate_n = normalize(candidate).strip()
        if not candidate_n:
            continue
        if required == candidate_n or required in candidate_n or candidate_n in required:
            return True
    return False


def calculate_skill_score(job_text: str, candidate_skills: list[str]):
    job_skills = [skill for skill in KNOWN_DEVOPS_SKILLS if contains_term(job_text, skill)]
    if not job_skills:
        return 0, [], []

    matched = []
    missing = []
    candidate_skills = candidate_skills or []

    for skill in job_skills:
        if _skill_matches(skill, candidate_skills):
            matched.append(skill)
        else:
            missing.append(skill)

    # Skill score is capped at 60. Coverage matters, but one matching skill
    # cannot create an artificially high score by itself.
    coverage = len(matched) / len(job_skills)
    breadth_bonus = min(len(matched), 5) * 5
    coverage_bonus = round(coverage * 35)
    skill_score = min(60, breadth_bonus + coverage_bonus)

    return skill_score, matched, missing


def calculate_role_score(job_title: str, target_roles: list[str]):
    title = str(job_title or "")

    if any(contains_term(title, term) for term in NON_DEVOPS_ROLE_TERMS):
        return 0

    if target_roles and any(contains_term(title, role) for role in target_roles):
        return 20

    if any(contains_term(title, term) for term in PRIMARY_ROLE_TERMS):
        return 20

    if any(contains_term(title, term) for term in SECONDARY_ROLE_TERMS):
        return 15

    return 0


def calculate_location_score(job_location: str, preferred_locations: list[str]):
    if not preferred_locations:
        return 10
    return 10 if any(contains_term(job_location, location) for location in preferred_locations) else 0


def calculate_experience_score(job_text: str, candidate_experience: float):
    text = str(job_text or "").lower()
    required_years = extract_required_years(text)
    if required_years is None:
        return 10, None
    if required_years <= candidate_experience:
        return 10, required_years
    # For a range such as 4-10 years, the lower bound is the real minimum.
    # A 3.5-year candidate is close enough to receive partial credit, but not full credit.
    if required_years <= candidate_experience + 0.5:
        return 7, required_years
    if required_years <= candidate_experience + 1:
        return 5, required_years
    return 0, required_years


def score_job(job: Any, profile: CandidateProfile):
    title = str(getattr(job, "title", "") or "")
    description = str(getattr(job, "description", "") or "")
    location = _job_location(job)
    company = _job_company(job)
    url = _job_url(job)

    job_text = f"{title}\n{company}\n{location}\n{description}"
    candidate_skills = get_list(profile.skills)
    target_roles = get_list(profile.target_roles)
    preferred_locations = get_list(profile.preferred_locations)

    skill_score, matched_skills, missing_skills = calculate_skill_score(job_text, candidate_skills)
    role_score = calculate_role_score(title, target_roles)
    location_score = calculate_location_score(location, preferred_locations)
    experience_score, required_years = calculate_experience_score(job_text, profile.years_experience)

    total_score = min(100, skill_score + role_score + location_score + experience_score)

    if role_score >= 20 and skill_score >= 35 and total_score >= 85:
        decision = "APPLY"
    elif role_score >= 15 and skill_score >= 20 and total_score >= 70:
        decision = "REVIEW"
    else:
        decision = "SKIP"

    return {
        "score": total_score,
        "decision": decision,
        "skill_score": skill_score,
        "role_score": role_score,
        "location_score": location_score,
        "experience_score": experience_score,
        "required_experience": required_years,
        "matched_skills": matched_skills,
        "missing_skills": missing_skills,
        "company": company,
        "location": location,
        "url": url,
    }
