"""
core/resume_nlp.py

Basic NLP layer built on top of Day 23's cleaned resume text:
tokenization, frequency-based keyword extraction, regex-based skill/
role/education pattern matching, years-of-experience extraction, and
one structured JSON schema tying it all together.

Deliberately rule-based / regex-based rather than ML-based, per the
Day 24 scope of "NLP basics" — "ML-ready outputs" means producing
clean, structured data a future ML step could consume (e.g. a flat
skill list with mention counts), not building the ML model itself.
"""

import re
from collections import Counter
from typing import Optional


def _normalize_separators(text: str) -> str:
    """
    Real resumes write compound terms inconsistently — 'Full-Stack',
    'Full Stack', and 'Fullstack' all mean the same thing. Regex
    matching against a fixed library needs one consistent form, so
    this replaces a hyphen between two word characters with a space
    before matching (used only for skill/role matching — NOT for
    email/phone extraction, where hyphens are meaningful).
    """
    return re.sub(r"(?<=\w)-(?=\w)", " ", text)


# ---------------------------------------------------------------------------
# 1. NLP Introduction: tokenization, keyword extraction
# ---------------------------------------------------------------------------

STOPWORDS = {
    "the", "and", "for", "with", "a", "an", "in", "on", "of", "to", "is",
    "are", "was", "were", "as", "at", "by", "or", "from", "this", "that",
    "it", "be", "has", "have", "had", "i", "we", "our", "their", "will",
    "using", "used", "use", "you", "your",
}


def tokenize(text: str) -> list:
    """
    Lowercase word tokenization. Matches letters/digits plus '+', '#',
    '.' so tokens like 'c++', 'c#', and 'node.js' survive as single
    tokens instead of being shredded by a naive \\w+ split.
    """
    return re.findall(r"[a-zA-Z][a-zA-Z0-9+#.]*", text.lower())


def extract_keywords(text: str, top_n: int = 20) -> list:
    """
    Basic frequency-based keyword extraction: tokenize, drop stopwords
    and very short tokens, return the N most frequent remaining words.
    """
    tokens = [t for t in tokenize(text) if len(t) > 2 and t not in STOPWORDS]
    counts = Counter(tokens)
    return [word for word, _ in counts.most_common(top_n)]


# ---------------------------------------------------------------------------
# 2. Skill Mapping: predefined library + regex matching
# ---------------------------------------------------------------------------

# A small, curated skills library. In a larger system this would likely
# live in the database so it can grow without a code change — kept as a
# constant here for Day 24's scope.
SKILLS_LIBRARY = [
    "Python", "Java", "JavaScript", "TypeScript", "C++", "C#", "Go", "Ruby",
    "PHP", "SQL", "HTML", "CSS",
    "Django", "Django REST Framework", "Flask", "FastAPI", "React", "Angular",
    "Vue", "Node.js", "Express",
    "PostgreSQL", "MySQL", "SQLite", "MongoDB", "Redis",
    "Git", "GitHub", "Docker", "Kubernetes", "AWS", "Azure", "GCP",
    "REST", "REST APIs", "GraphQL", "JWT", "OAuth",
    "Machine Learning", "Deep Learning", "NLP", "Pandas", "NumPy",
    "TensorFlow", "PyTorch", "Scikit-learn",
    "Agile", "Scrum", "CI/CD", "Linux",
]


def _skill_pattern(skill: str) -> re.Pattern:
    """Word-boundary regex for one skill. re.escape makes special
    characters (C++, C#, Node.js, CI/CD) safe to match literally."""
    escaped = re.escape(skill)
    return re.compile(rf"(?<![\w+#]){escaped}(?![\w+#])", re.IGNORECASE)


_SKILL_PATTERNS = [(skill, _skill_pattern(skill)) for skill in SKILLS_LIBRARY]


def extract_skills(text: str) -> list:
    """
    Regex-match every skill in SKILLS_LIBRARY against the resume text.
    Returns an ML-ready list of {skill, mentions} dicts, sorted by
    mention count — a flat, structured format a downstream ranking or
    matching model could consume directly, rather than just a yes/no
    per skill. Hyphen/space variants are normalized before matching
    (see _normalize_separators), so 'Full-Stack' style phrasing doesn't
    cause a miss on multi-word entries.
    """
    normalized = _normalize_separators(text)
    results = []
    for skill, pattern in _SKILL_PATTERNS:
        mentions = len(pattern.findall(normalized))
        if mentions:
            results.append({"skill": skill, "mentions": mentions})
    results.sort(key=lambda r: r["mentions"], reverse=True)
    return results


# ---------------------------------------------------------------------------
# 3. Experience & Education Parsing
# ---------------------------------------------------------------------------

YEARS_PATTERN = re.compile(
    r"(\d+(?:\.\d+)?)\+?\s*(?:years|yrs|year)\b(?:\s*of\s*experience)?",
    re.IGNORECASE,
)

# Maps a matched keyword to the SAME level names used by the Candidate
# model's EDUCATION_CHOICES (Day 11), so results are directly comparable.
EDUCATION_KEYWORDS = {
    "phd": "phd",
    "ph.d": "phd",
    "doctorate": "phd",
    "master": "masters",
    "m.tech": "masters",
    "msc": "masters",
    "bachelor": "bachelors",
    "b.tech": "bachelors",
    "bsc": "bachelors",
    "high school": "high_school",
}

ROLE_LIBRARY = [
    "Full Stack Developer", "Backend Developer", "Frontend Developer",
    "Software Engineer", "Software Developer", "Web Developer",
    "Data Scientist", "Data Analyst", "Machine Learning Engineer",
    "DevOps Engineer", "QA Engineer", "Product Manager",
    "Project Manager", "UI/UX Designer", "Intern",
]


def extract_years_of_experience(text: str) -> Optional[float]:
    """
    Finds every 'X years [of experience]' style mention and returns the
    MAXIMUM value found. Resumes often repeat the headline figure (once
    in a summary, once in a section header); the largest stated number
    is the most representative total, rather than double-counting or
    just taking whichever mention happens to be first.
    """
    matches = YEARS_PATTERN.findall(text)
    if not matches:
        return None
    return max(float(m) for m in matches)


def extract_education(text: str) -> list:
    """Matches known education-level keywords, de-duplicated, in the
    order first seen."""
    text_lower = text.lower()
    found = []
    for keyword, level in EDUCATION_KEYWORDS.items():
        if keyword in text_lower and level not in found:
            found.append(level)
    return found


def extract_roles(text: str) -> list:
    """Matches known role titles against the resume text. Checked
    longest-first (see ROLE_LIBRARY ordering) so 'Full Stack Developer'
    matches as itself rather than also separately triggering on the
    word 'Developer' appearing inside it. Hyphen/space variants (e.g.
    'Full-Stack' vs 'Full Stack') are normalized before matching."""
    normalized = _normalize_separators(text)
    found = []
    for role in ROLE_LIBRARY:
        pattern = re.compile(rf"\b{re.escape(role)}\b", re.IGNORECASE)
        if pattern.search(normalized):
            found.append(role)
    return found


# ---------------------------------------------------------------------------
# Contact pattern matching — feeds the JSON schema's contact fields
# ---------------------------------------------------------------------------

EMAIL_PATTERN = re.compile(r"[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}")
PHONE_PATTERN = re.compile(r"(?:\+?\d{1,3}[-.\s]?)?\d{10}\b")


# ---------------------------------------------------------------------------
# 4. Data Structuring — the Resume JSON schema
# ---------------------------------------------------------------------------

def parse_resume(cleaned_text: str) -> dict:
    """
    Runs the full NLP pipeline over already-cleaned resume text (from
    Day 23's clean_text()) and returns one structured dict — the
    "Structured resume JSON" deliverable.
    """
    return {
        "keywords": extract_keywords(cleaned_text),
        "skills": extract_skills(cleaned_text),
        "years_of_experience": extract_years_of_experience(cleaned_text),
        "education": extract_education(cleaned_text),
        "detected_roles": extract_roles(cleaned_text),
        "emails": list(set(EMAIL_PATTERN.findall(cleaned_text))),
        "phones": list(set(PHONE_PATTERN.findall(cleaned_text))),
    }