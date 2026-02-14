"""
PDF Parser for document ingestion
"""

import logging
import subprocess
from pathlib import Path

# Module-level PyPDF2 import with error handling
try:
    from PyPDF2 import PdfReader
    PYPDF2_AVAILABLE = True
except ImportError:
    PdfReader = None
    PYPDF2_AVAILABLE = False

logger = logging.getLogger(__name__)


def extract_text_from_pdf(pdf_path: Path, max_pages: int = None) -> str:
    """
    Extract text from PDF using pdftotext or PyPDF2
    """
    pdf_path = Path(pdf_path)

    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    # Try pdftotext first (better quality)
    try:
        cmd = ["pdftotext", "-layout", str(pdf_path), "-"]
        if max_pages:
            cmd = ["pdftotext", "-layout", "-l", str(max_pages), str(pdf_path), "-"]

        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60
        )

        # Check stderr for warnings
        if result.stderr:
            logger.warning(f"pdftotext warnings for {pdf_path}: {result.stderr}")

        if result.returncode == 0:
            return result.stdout

    except subprocess.TimeoutExpired as e:
        logger.warning(f"pdftotext timed out for {pdf_path}: {e}")
    except subprocess.CalledProcessError as e:
        logger.warning(f"pdftotext failed for {pdf_path}: {e}")
    except FileNotFoundError as e:
        logger.debug(f"pdftotext not found, falling back to PyPDF2: {e}")

    # Fallback to PyPDF2
    if not PYPDF2_AVAILABLE:
        raise RuntimeError(
            "Cannot extract PDF text. Install pdftotext or PyPDF2.\n"
            "sudo apt install poppler-utils  OR  pip install PyPDF2"
        )

    # Verify file exists immediately before PdfReader call
    if not pdf_path.exists():
        raise FileNotFoundError(f"PDF not found: {pdf_path}")

    reader = PdfReader(str(pdf_path))
    pages_to_read = len(reader.pages)
    if max_pages:
        pages_to_read = min(max_pages, pages_to_read)

    text_parts = []
    for i in range(pages_to_read):
        page = reader.pages[i]
        text = page.extract_text()
        # Handle None return from extract_text() gracefully
        if text is not None and text:
            text_parts.append(text)

    return "\n\n".join(text_parts)


def get_pdf_metadata(pdf_path: Path) -> dict:
    """Extract PDF metadata"""
    pdf_path = Path(pdf_path)

    if not PYPDF2_AVAILABLE:
        logger.warning("PyPDF2 not available, cannot extract PDF metadata")
        return {}

    # Verify file exists immediately before PdfReader call
    if not pdf_path.exists():
        logger.error(f"PDF not found for metadata extraction: {pdf_path}")
        return {}

    try:
        reader = PdfReader(str(pdf_path))
        metadata = reader.metadata

        return {
            "title": metadata.get("/Title", ""),
            "author": metadata.get("/Author", ""),
            "subject": metadata.get("/Subject", ""),
            "creator": metadata.get("/Creator", ""),
            "pages": len(reader.pages)
        }
    except Exception as e:
        logger.error(f"Failed to extract PDF metadata from {pdf_path}: {type(e).__name__}: {e}")
        return {}
