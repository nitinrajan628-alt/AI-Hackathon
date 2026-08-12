"""Report slide retrieval: review-filtered FTS5 search with weighted
ranking, stable citations, and slide access for the report viewer.

Supports both legacy structured rendering (JSON content) and the new
PowerPoint-based display (pre-rendered PNG images from .pptx files).
"""
from __future__ import annotations

import json
import os
import re

from models.evidence import SlideEvidence
from services.db import get_review_connection
from services.review_service import quarter_label

EXCERPT_CHARS = 900
REPORTS_DIR = os.path.join(os.path.dirname(__file__), "..", "data", "reports")


def _fts_query(query: str) -> str:
    """Sanitise free text into an FTS5 OR-query of plain terms."""
    words = re.findall(r"[A-Za-z0-9]{2,}", query.lower())
    stop = {"the", "and", "for", "this", "that", "what", "does", "say", "says",
            "about", "are", "our", "of", "in", "on", "to", "is", "it", "an",
            "from", "with", "how", "much", "did", "was", "were"}
    terms = [w for w in words if w not in stop]
    if not terms:
        return ""
    return " OR ".join(f'"{t}"' for t in terms[:12])


def search_slides(review_ids: list[str], query: str,
                  limit: int = 5) -> list[SlideEvidence]:
    match = _fts_query(query)
    if not match or not review_ids:
        return []
    limit = max(1, min(limit, 5))
    con = get_review_connection()
    try:
        placeholders = ",".join("?" for _ in review_ids)
        rows = con.execute(
            f"""
            SELECT f.slide_id, f.review_id,
                   bm25(slide_fts, 0.0, 0.0, 5.0, 2.0, 1.0, 3.0) AS score,
                   s.slide_number, s.title, s.section, s.plain_text
            FROM slide_fts f
            JOIN report_slide s ON s.slide_id = f.slide_id
            WHERE slide_fts MATCH ? AND f.review_id IN ({placeholders})
            ORDER BY score LIMIT ?
            """,
            [match, *review_ids, limit],
        ).fetchall()
    finally:
        con.close()
    out = []
    for r in rows:
        out.append(SlideEvidence(
            evidence_id=f"slide_{r['slide_id']}",
            slide_id=r["slide_id"], review_id=r["review_id"],
            quarter_label=quarter_label(r["review_id"]),
            slide_number=r["slide_number"], title=r["title"],
            section=r["section"], excerpt=r["plain_text"][:EXCERPT_CHARS],
            score=-float(r["score"]),
        ))
    return out


def list_slides(review_id: str) -> list[dict]:
    con = get_review_connection()
    try:
        rows = con.execute(
            "SELECT slide_id, review_id, slide_number, section, title, "
            "content_json, tags_json FROM report_slide WHERE review_id=? "
            "ORDER BY slide_number", (review_id,)).fetchall()
    finally:
        con.close()
    slides = []
    for r in rows:
        d = dict(r)
        d["content"] = json.loads(d.pop("content_json"))
        d["tags"] = json.loads(d.pop("tags_json"))
        slides.append(d)
    return slides


def get_slide(review_id: str, slide_number: int) -> dict | None:
    for s in list_slides(review_id):
        if s["slide_number"] == slide_number:
            return s
    return None


# ---------------------------------------------------------------------------
# PowerPoint-based report functions
# ---------------------------------------------------------------------------

def has_pptx_report(review_id: str) -> bool:
    """Check whether a pre-built .pptx report exists for this review."""
    manifest_path = os.path.join(REPORTS_DIR, review_id, "manifest.json")
    return os.path.isfile(manifest_path)


def get_report_manifest(review_id: str) -> dict | None:
    """Load the manifest JSON for a review's slide deck."""
    manifest_path = os.path.join(REPORTS_DIR, review_id, "manifest.json")
    if not os.path.isfile(manifest_path):
        return None
    with open(manifest_path) as f:
        return json.load(f)


def get_slide_image_path(review_id: str, slide_index: int) -> str | None:
    """Return the filesystem path to a slide PNG image (1-indexed)."""
    png_file = os.path.join(REPORTS_DIR, review_id, f"slide_{slide_index:02d}.png")
    if os.path.isfile(png_file):
        return png_file
    return None


def get_pptx_path(review_id: str) -> str | None:
    """Return the filesystem path to the .pptx file for download."""
    pptx_file = os.path.join(REPORTS_DIR, review_id, f"{review_id}.pptx")
    if os.path.isfile(pptx_file):
        return pptx_file
    return None


def get_pptx_bytes(review_id: str) -> bytes | None:
    """Return the .pptx file contents as bytes for download."""
    path = get_pptx_path(review_id)
    if path is None:
        return None
    with open(path, "rb") as f:
        return f.read()
