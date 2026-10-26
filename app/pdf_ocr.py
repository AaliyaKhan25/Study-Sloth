"""Extract selectable text from PDFs and use the configured vision model for scanned pages."""
import io
import os
from concurrent.futures import ThreadPoolExecutor, as_completed

from .llm import chat

MAX_OCR_PAGES = int(os.environ.get("SLOTH_OCR_MAX_PAGES", 30))
OCR_WORKERS = 2


def _read_scanned_page(source, page_number):
    import fitz

    if isinstance(source, bytes):
        document = fitz.open(stream=source, filetype="pdf")
    else:
        document = fitz.open(source)
    try:
        page = document.load_page(page_number)
        image = page.get_pixmap(matrix=fitz.Matrix(1.5, 1.5), alpha=False).tobytes("png")
    finally:
        document.close()
    text = chat(
        "Transcribe all visible text from this scanned document page in reading order. "
        "Preserve headings, formulas, lists, and table rows as accurately as possible. "
        "Do not summarize or add information. If the page has no readable text, return an empty response.",
        images=[image],
        num_predict=3000,
        timeout=180,
    ).strip()
    return text


def extract_pdf_pages(source, max_pages=None, progress=None):
    from pypdf import PdfReader

    reader_source = io.BytesIO(source) if isinstance(source, bytes) else source
    reader = PdfReader(reader_source)
    total_pages = len(reader.pages)
    page_limit = min(total_pages, max_pages) if max_pages is not None else total_pages
    pages = []
    scanned = []
    for index, page in enumerate(reader.pages[:page_limit]):
        text = (page.extract_text() or "").strip()
        if text:
            pages.append((index + 1, text))
        else:
            scanned.append(index)

    if len(scanned) > MAX_OCR_PAGES:
        raise ValueError(
            f"This PDF has {len(scanned)} pages that need OCR; the current limit is "
            f"{MAX_OCR_PAGES}. Split the PDF into smaller files and try again."
        )

    if scanned:
        results = {}
        with ThreadPoolExecutor(max_workers=min(OCR_WORKERS, len(scanned))) as executor:
            futures = {
                executor.submit(_read_scanned_page, source, index): index
                for index in scanned
            }
            for completed, future in enumerate(as_completed(futures), 1):
                index = futures[future]
                text = future.result()
                if text:
                    results[index + 1] = text
                if progress:
                    progress(completed, len(scanned), index + 1)
        pages.extend(results.items())

    pages.sort(key=lambda item: item[0])
    if not pages:
        raise ValueError(
            "No readable text was found in this PDF, even after OCR. Check that the pages are clear."
        )
    return pages, total_pages, bool(scanned)
