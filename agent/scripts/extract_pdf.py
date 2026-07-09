#!/usr/bin/env python3
"""Extract text from a PDF using pdf_oxide and write it to a Markdown file.

Reusable across agent runs — does not get re-invented each ingest.

Usage:
    python extract_pdf.py <input.pdf> <output.md> [--max-pages N] [--start-page N]

Output: a Markdown file with one section per page:
    # Page 1
    <extracted text>
    # Page 2
    <extracted text>
    ...

The page headers let read_file (with offset/limit) consume pages one at a time.
"""
from __future__ import annotations

import argparse
import sys
from pathlib import Path


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("input", type=Path, help="PDF file to extract")
    parser.add_argument("output", type=Path, help="Output Markdown file")
    parser.add_argument("--max-pages", type=int, default=0,
                        help="Max pages to extract (0 = all). Default: 0")
    parser.add_argument("--start-page", type=int, default=0,
                        help="0-indexed page to start from. Default: 0")
    args = parser.parse_args()

    if not args.input.is_file():
        print(f"ERROR: input not found: {args.input}", file=sys.stderr)
        return 2

    try:
        from pdf_oxide import PdfDocument
    except ImportError as e:
        print(f"ERROR: pdf_oxide not installed: {e}", file=sys.stderr)
        print("Run: <python> -m pip install pdf_oxide", file=sys.stderr)
        return 3

    try:
        doc = PdfDocument(str(args.input))
    except Exception as e:
        print(f"ERROR: cannot open PDF: {e}", file=sys.stderr)
        return 4

    total = doc.page_count()
    start = max(0, args.start_page)
    end = total if args.max_pages <= 0 else min(total, start + args.max_pages)
    args.output.parent.mkdir(parents=True, exist_ok=True)

    with args.output.open("w", encoding="utf-8") as f:
        f.write(f"# Extracted from {args.input.name}\n\n")
        f.write(f"> Total pages: {total} | Extracted: pages {start}..{end - 1}\n\n")
        for i in range(start, end):
            try:
                text = doc.to_markdown(i)
            except Exception as e:
                text = f"<!-- page {i} extraction failed: {e} -->"
            f.write(f"# Page {i + 1}\n\n")
            f.write(text)
            f.write("\n\n")

    print(f"OK pages={end - start} total={total} out={args.output}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
