import re

from app.models import CandidateProfile, Job

KNOWN_DEVOPS_SKILLS = [
    "AWS",
    "Azure",
    "GCP",
    "Kubernetes",
    "Docker",
    "Terraform",
    "Jenkins",
    "Azure DevOps",
    "GitHub Actions",
    "GitLab CI",
    "OpenShift",
    "Linux",
    "Bash",
    "Python",
    "Helm",
    "Ansible",
    "ArgoCD",
    "Prometheus",
    "Grafana",
    "Istio",
    "Vault",
    "Packer",
    "CloudFormation",
    "EKS",
    "AKS",
    "GKE",
]

def normalize(text: str) -> str:
    """
    Convert text to a simple comparable format.
    """
    return re.sub(
        r"[^a-z0-9+#.\- ]+",
        " ",
        text.lower()
    )


def contains_term(text: str, term: str) -> bool:
    """
    Check whether a term exists in text.
    """
    text = normalize(text)
    term = normalize(term).strip()

    return term in text


def get_list(value: str) -> list[str]:
    """
    Convert comma-separated database value into a list.
    """
    return [
        item.strip()
        for item in value.split(",")
        if item.strip()
    ]


def extract_required_years(text: str):
    """
    Try to detect experience requirements such as:

    3+ years
    4 years
    3-5 years
    2 yrs
    """

    text = text.lower()

    patterns = [
        r"(\d+(?:\.\d+)?)\s*\+\s*(?:years|yrs)",
        r"(\d+(?:\.\d+)?)\s*(?:years|yrs)\s*(?:of)?\s*experience",
        r"(\d+(?:\.\d+)?)\s*-\s*(\d+(?:\.\d+)?)\s*(?:years|yrs)"
    ]

    for pattern in patterns:

        match = re.search(pattern, text)

        if match:
            return float(match.group(1))

    return None


def calculate_skill_score(
    job_text: str,
    candidate_skills: list[str]
):
    """
    Compare the candidate against the DevOps skills
    actually mentioned in the job description.
    """

    job_skills = []

    for skill in KNOWN_DEVOPS_SKILLS:

        if contains_term(job_text, skill):
            job_skills.append(skill)

    if not job_skills:
        return 30, [], []

    matched = []

    missing = []

    for skill in job_skills:

        if any(
            contains_term(skill, candidate_skill)
            or contains_term(candidate_skill, skill)
            for candidate_skill in candidate_skills
        ):
            matched.append(skill)

        else:
            missing.append(skill)

    score = (
        len(matched)
        / len(job_skills)
        * 60
    )

    return round(score), matched, missing

def calculate_role_score(
    job_title: str,
    target_roles: list[str]
):

    for role in target_roles:

        if contains_term(job_title, role):
            return 20

    return 0


def calculate_location_score(
    job_location: str,
    preferred_locations: list[str]
):

    if not preferred_locations:
        return 10

    for location in preferred_locations:

        if contains_term(
            job_location,
            location
        ):
            return 10

    return 0


def calculate_experience_score(
    job_text: str,
    candidate_experience: float
):

    required_years = extract_required_years(
        job_text
    )

    # If we cannot determine the requirement,
    # don't penalize the candidate.
    if required_years is None:
        return 10, None

    if required_years <= candidate_experience:
        return 10, required_years

    if required_years <= candidate_experience + 1:
        return 5, required_years

    return 0, required_years


def score_job(
    job: Job,
    profile: CandidateProfile
):

    job_text = f"""
    {job.title}
    {job.description}
    """

    candidate_skills = get_list(
        profile.skills
    )

    target_roles = get_list(
        profile.target_roles
    )

    preferred_locations = get_list(
        profile.preferred_locations
    )

    # -------------------------
    # Skills
    # -------------------------

    skill_score, matched_skills, missing_skills = (
        calculate_skill_score(
            job_text,
            candidate_skills
        )
    )

    # -------------------------
    # Role
    # -------------------------

    role_score = calculate_role_score(
        job.title,
        target_roles
    )

    # -------------------------
    # Location
    # -------------------------

    location_score = calculate_location_score(
        job.location,
        preferred_locations
    )

    # -------------------------
    # Experience
    # -------------------------

    experience_score, required_years = (
        calculate_experience_score(
            job_text,
            profile.years_experience
        )
    )

    # -------------------------
    # Final score
    # -------------------------

    total_score = min(
        100,
        skill_score
        + role_score
        + location_score
        + experience_score
    )

    # -------------------------
    # Decision
    # -------------------------

    if total_score >= 85:
        decision = "APPLY"

    elif total_score >= 70:
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
        "missing_skills": missing_skills
    }
