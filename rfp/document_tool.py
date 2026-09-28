"""Document Tool: extract clean, page-tagged text from a PDF."""
import re

import pymupdf


def extract_text(pdf_bytes):
    """Returns (text, page_count). Raises ValueError for files that aren't readable PDFs."""
    try:
        doc = pymupdf.open(stream=pdf_bytes, filetype="pdf")
    except Exception as e:  # pymupdf raises its own FileDataError / RuntimeError variants
        raise ValueError(f"not a readable PDF ({e})") from e
    with doc:
        pages = []
        for i, page in enumerate(doc, start=1):
            # expand ligatures (ﬀ -> ff) so evidence quotes are plain text
            text = page.get_text("text", flags=pymupdf.TEXTFLAGS_TEXT & ~pymupdf.TEXT_PRESERVE_LIGATURES)
            text = re.sub(r"[ \t]+", " ", text)
            text = re.sub(r"\n\s*\n+", "\n", text).strip()
            if text:
                pages.append(f"[Page {i}]\n{text}")
        return "\n\n".join(pages), doc.page_count


def extract_metadata(text):
    """Pre-fill supplier metadata when the proposal states it, e.g. "Apex Systems — Synthetic RFP Response",
    "Submission date: 2026-08-20", "Historical experience rating: 8/10". Missing fields are None; the user confirms."""
    body = re.sub(r"\[Page \d+\]", "", text).strip()
    first = body.splitlines()[0].strip() if body else ""
    name = re.match(r"(.+?)\s+[—–-]\s+.*\b(RFP|Proposal|Response)\b", first, re.I)
    date = re.search(r"Submission date:?\s*(\d{4}-\d{2}-\d{2})", body, re.I)
    rating = re.search(r"experience rating:?\s*(\d+(?:\.\d+)?)\s*(?:/\s*10)?", body, re.I)
    return {"supplier_name": name.group(1).strip() if name else None,
            "submission_date": date.group(1) if date else None,
            "experience_rating": float(rating.group(1)) if rating else None}
