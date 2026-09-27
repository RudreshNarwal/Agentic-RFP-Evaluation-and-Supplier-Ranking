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
