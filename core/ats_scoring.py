"""
core/ats_scoring.py

ATS scoring service: compares a Candidate's resume-derived data
against a Job's requirements and produces one normalized suitability
score (0-100%), broken down into skills / experience / education
sub-scores.
"""

import re

from .resume_parser import extract_text, clean_text
from .resume_nlp import parse_resume, _normalize_separators


# ---------------------------------------------------------------------------
# 1. Scoring Model Design — weights & reference tables
# ---------------------------------------------------------------------------

SKILLS_WEIGHT = 0.55
EXPERIENCE_WEIGHT = 0.30
EDUCATION_WEIGHT = 0.15

# Job.experience bracket -> (min_years, max_years). max=None means
# "no upper bound" (not currently used for scoring, kept for clarity).
EXPERIENCE_BRACKETS = {
    "fresher": (0, 0),
    "0-1": (0, 1),
    "1-3": (1, 3),
    "3-5": (3, 5),
    "5+": (5, None),
}

# Ordinal ranking so "meets or exceeds" is a simple integer comparison.
EDUCATION_RANK = {
    "high_school": 1,
    "bachelors": 2,
    "masters": 3,
    "phd": 4,
}


def _job_skill_keywords(job_skills_text: str) -> list:
    """A Job's `skills` field is free-text, comma-separated (e.g.
    'Python, Django, PostgreSQL') — split into individual keywords."""
    return [s.strip() for s in job_skills_text.split(",") if s.strip()]


def score_skills(job_skills_text: str, candidate_resume_text: str) -> dict:
    """
    What fraction of the JOB's required skills are found in the
    candidate's resume text. Case-insensitive, hyphen/space-normalized
    substring matching (same approach as Day 24's extract_skills),
    since job skills are free text, not guaranteed to come from a
    fixed library.
    """
    required = _job_skill_keywords(job_skills_text)
    if not required:
        return {"score": 100.0, "matched": [], "required": [], "total_required": 0}

    normalized_resume = _normalize_separators(candidate_resume_text)
    matched = []
    for skill in required:
        pattern = re.compile(
            rf"(?<![\w+#]){re.escape(_normalize_separators(skill))}(?![\w+#])",
            re.IGNORECASE,
        )
        if pattern.search(normalized_resume):
            matched.append(skill)

    score = (len(matched) / len(required)) * 100
    return {
        "score": round(score, 1),
        "matched": matched,
        "required": required,
        "total_required": len(required),
    }


def score_experience(job_experience_bracket: str, candidate_years) -> dict:
    """
    How well the candidate's years of experience fits the job's
    bracket: full score at/above the bracket's minimum (more
    experience than asked for is never penalized here — treating
    "overqualified" as disqualifying is a business judgment call, not
    a matching rule); linearly-decaying partial score below it.
    """
    bracket = EXPERIENCE_BRACKETS.get(job_experience_bracket)
    if bracket is None or candidate_years is None:
        return {"score": 50.0, "reason": "insufficient_data"}

    min_years, _max_years = bracket

    if min_years == 0 or candidate_years >= min_years:
        return {"score": 100.0, "reason": "meets_or_exceeds_minimum"}

    ratio = max(candidate_years / min_years, 0)
    return {"score": round(ratio * 100, 1), "reason": "below_minimum"}


def score_education(job_required_education: str, candidate_education: str) -> dict:
    """
    Full marks if the job has no stated requirement, or the candidate
    meets/exceeds it. Otherwise partial credit that shrinks with the
    size of the gap (one level below still scores something; two or
    more levels below scores very low).
    """
    if not job_required_education:
        return {"score": 100.0, "reason": "no_requirement"}

    required_rank = EDUCATION_RANK.get(job_required_education)
    candidate_rank = EDUCATION_RANK.get(candidate_education)

    if required_rank is None or candidate_rank is None:
        return {"score": 50.0, "reason": "insufficient_data"}

    if candidate_rank >= required_rank:
        return {"score": 100.0, "reason": "meets_or_exceeds_requirement"}

    gap = required_rank - candidate_rank
    return {"score": round(max(100 - gap * 40, 0), 1), "reason": "below_requirement"}


# ---------------------------------------------------------------------------
# 2. Match Algorithm — combine + normalize
# ---------------------------------------------------------------------------

def compute_ats_score(job, candidate) -> dict:
    """
    Full pipeline for one (job, candidate) pair: extract + parse the
    candidate's resume, score skills/experience/education against the
    job's requirements, and combine into one normalized 0-100
    suitability percentage.
    """
    if not candidate.resume:
        return {"suitability_percent": 0.0, "error": "Candidate has no resume on file."}

    candidate.resume.open("rb")
    try:
        raw_text = extract_text(candidate.resume, candidate.resume.name)
    except ValueError as e:
        return {"suitability_percent": 0.0, "error": str(e)}
    finally:
        candidate.resume.close()

    cleaned = clean_text(raw_text)
    parsed = parse_resume(cleaned)

    # Prefer the resume's own stated years of experience (Day 24); fall
    # back to the candidate's self-reported profile field (Day 11)
    # rather than treating it as missing when the resume just doesn't
    # spell out a number.
    candidate_years = parsed["years_of_experience"]
    if candidate_years is None:
        candidate_years = candidate.experience_years

    skills_result = score_skills(job.skills, cleaned)
    experience_result = score_experience(job.experience, candidate_years)
    education_result = score_education(
        getattr(job, "required_education", ""), candidate.education
    )

    weighted_total = (
        skills_result["score"] * SKILLS_WEIGHT
        + experience_result["score"] * EXPERIENCE_WEIGHT
        + education_result["score"] * EDUCATION_WEIGHT
    )

    return {
        "suitability_percent": round(weighted_total, 1),
        "breakdown": {
            "skills": skills_result,
            "experience": experience_result,
            "education": education_result,
        },
        "weights": {
            "skills": SKILLS_WEIGHT,
            "experience": EXPERIENCE_WEIGHT,
            "education": EDUCATION_WEIGHT,
        },
    }