"""
core/resume_parser.py

Text extraction and cleaning for resume files — the document
intelligence / AI-preprocessing layer. Two formats are supported:

- PDF via pdfplumber: pdfplumber reconstructs reading order from each
  page's positioned text, which handles simple single/multi-column
  resumes reasonably well without external system dependencies.
- DOCX via python-docx: DOCX is a zip of structured XML, so paragraphs
  and table cells are read directly rather than reconstructed from
  layout — generally more reliable than PDF extraction.
- Legacy .doc (pre-2007 binary format) is explicitly NOT supported:
  it needs different tooling (e.g. antiword) that isn't part of this
  pipeline. Callers get a clear error rather than silently wrong text.
"""

import re
import unicodedata

import pdfplumber
import docx  # python-docx


def extract_text_from_pdf(file_obj) -> str:
    """Extract text from a PDF, page by page, in reading order."""
    text_parts = []
    with pdfplumber.open(file_obj) as pdf:
        for page in pdf.pages:
            text_parts.append(page.extract_text(x_tolerance=1) or "")
    return "\n".join(text_parts)


def extract_text_from_docx(file_obj) -> str:
    """Extract text from a DOCX: paragraphs, plus table cells (resumes
    frequently use tables for layout, e.g. skills columns)."""
    document = docx.Document(file_obj)
    parts = [p.text for p in document.paragraphs]
    for table in document.tables:
        for row in table.rows:
            for cell in row.cells:
                if cell.text.strip():
                    parts.append(cell.text)
    return "\n".join(parts)


def extract_text(file_obj, filename: str) -> str:
    """Dispatch to the right extractor based on file extension."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    file_obj.seek(0)

    if ext == "pdf":
        return extract_text_from_pdf(file_obj)
    if ext == "docx":
        return extract_text_from_docx(file_obj)
    if ext == "doc":
        raise ValueError(
            "Legacy .doc files aren't supported for text extraction — "
            "please upload PDF or DOCX instead. (.doc is a proprietary "
            "binary format; DOCX is a parseable zip/XML structure, which "
            "is why they need different tooling.)"
        )
    raise ValueError(f"Unsupported file type: .{ext}")


def clean_text(raw_text: str) -> str:
    """
    Normalize and de-noise extracted resume text:
    - Unicode normalization (smart quotes, ligatures -> plain forms)
    - Strip non-printable/control characters
    - Collapse repeated spaces/tabs and excessive blank lines
    - Strip common resume noise: page-number lines ("Page 1 of 2", or
      a lone "1"/"2" left over from a footer)
    """
    if not raw_text:
        return ""

    text = unicodedata.normalize("NFKC", raw_text)
    text = "".join(ch for ch in text if ch in "\n\t" or ch.isprintable())
    text = re.sub(r"[ \t]+", " ", text)
    text = "\n".join(line.strip() for line in text.split("\n"))

    # Noise removal: page-number lines and lone-number footer lines
    text = re.sub(r"(?im)^\s*page\s+\d+\s*(of\s*\d+)?\s*$", "", text)
    text = re.sub(r"(?m)^\s*\d{1,3}\s*$", "", text)

    # Collapse blank lines (do this last, after noise lines are removed)
    text = re.sub(r"\n{3,}", "\n\n", text)

    return text.strip()