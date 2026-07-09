"""extract_pdf tool — runs the reusable extraction script and writes output
to a known location under WIKI_ROOT, so the agent can read the result
page by page via read_file.

The underlying script lives at agent/scripts/extract_pdf.py and is
checked into the repo. This tool just shells out to it with the right
interpreter and validates inputs.

Why a tool rather than raw bash:
  - Output path is deterministic (WIKI_ROOT/.cache/extract/<doc_id>.md)
    so read_file / offset / limit Just Work across re-ingests.
  - No need to type long python -c invocations from the agent.
  - The extraction script is the same across all ingests, so the
    output format is stable and cacheable.
"""

import logging
import subprocess
import sys
from pathlib import Path

from config import PYTHON_BIN, WIKI_ROOT

logger = logging.getLogger(__name__)

DESCRIPTION = """Extract text from a PDF file to a Markdown file under WIKI_ROOT.

Uses the reusable script at agent/scripts/extract_pdf.py with the configured
Python interpreter (one that has pdf_oxide installed). The output goes to
WIKI_ROOT/.cache/extract/<doc_id>.md, written with one section per page so
read_file (with offset/limit) can consume pages incrementally.

Use this when ingesting a PDF source — don't write your own extraction code.
After extracting, use read_file on the output path to read pages of text.

Args:
  pdf_path:     PDF file path, relative to WIKI_ROOT (e.g. 'main/sources/004__foo/paper.pdf')
  doc_id:       Used to name the output cache file (e.g. '004__foo'). Optional
                — defaults to the parent dir name of pdf_path.
  max_pages:    Limit pages extracted (0 = all). Useful for very long PDFs.
  start_page:   0-indexed page to start from.

Returns:
  {ok, output_path, pages, total_pages, total_chars, ...} on success
  {error, stderr} on failure"""

JSON_SCHEMA: dict = {
    "type": "object",
    "properties": {
        "pdf_path": {
            "type": "string",
            "description": "PDF file path relative to WIKI_ROOT.",
        },
        "doc_id": {
            "type": "string",
            "description": "Doc identifier used to name the cache file. Default: parent dir of pdf_path.",
        },
        "max_pages": {
            "type": "integer",
            "description": "Limit on pages to extract. 0 = extract all (default).",
            "default": 0,
        },
        "start_page": {
            "type": "integer",
            "description": "0-indexed page to start from. Default: 0.",
            "default": 0,
        },
    },
    "required": ["pdf_path"],
}

CACHE_DIR = WIKI_ROOT / ".cache" / "extract"
SCRIPT_PATH = Path(__file__).resolve().parent.parent / "scripts" / "extract_pdf.py"


def execute(pdf_path: str, doc_id: str = "", max_pages: int = 0, start_page: int = 0) -> dict:
    """Run the extraction script and return its result.

    Returns a dict suitable for the model: success → metadata, failure → error.
    """
    # Resolve input PDF
    pdf_full = (WIKI_ROOT / pdf_path).resolve()
    try:
        pdf_full.relative_to(WIKI_ROOT.resolve())
    except ValueError:
        return {"error": f"pdf_path {pdf_path!r} escapes WIKI_ROOT"}
    if not pdf_full.is_file():
        return {"error": f"PDF not found: {pdf_path}"}

    # Derive doc_id from parent dir if not given
    if not doc_id:
        doc_id = pdf_full.parent.name

    # Determine output path
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    out_path = CACHE_DIR / f"{doc_id}.md"

    # Sanity check: script exists
    if not SCRIPT_PATH.is_file():
        return {"error": f"extraction script missing: {SCRIPT_PATH}"}

    # Sanity check: python interpreter
    py = PYTHON_BIN or sys.executable

    # Build command
    cmd = [py, str(SCRIPT_PATH), str(pdf_full), str(out_path)]
    if max_pages and max_pages > 0:
        cmd += ["--max-pages", str(max_pages)]
    if start_page and start_page > 0:
        cmd += ["--start-page", str(start_page)]

    logger.info("extract_pdf: %s -> %s (max=%d start=%d)",
                pdf_full, out_path, max_pages, start_page)

    try:
        result = subprocess.run(
            cmd, capture_output=True, encoding="utf-8", errors="replace",
            timeout=300,
        )
    except subprocess.TimeoutExpired:
        return {"error": f"extraction timed out after 300s (PDF too large?)"}
    except Exception as e:
        return {"error": f"failed to run extraction script: {e}"}

    if result.returncode != 0:
        return {
            "error": f"extraction failed (exit {result.returncode})",
            "stderr": (result.stderr or "").strip(),
            "stdout": (result.stdout or "").strip(),
        }

    if not out_path.is_file():
        return {"error": "extraction script returned 0 but output file is missing"}

    # Count pages (lines starting with "# Page ")
    text = out_path.read_text(encoding="utf-8", errors="replace")
    page_count = sum(1 for line in text.splitlines() if line.startswith("# Page "))
    total_chars = len(text)

    return {
        "ok": True,
        "output_path": str(out_path.relative_to(WIKI_ROOT)),
        "pages": page_count,
        "total_chars": total_chars,
        "stdout": (result.stdout or "").strip(),
    }
