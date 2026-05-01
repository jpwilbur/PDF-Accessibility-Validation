"""Machine-readable outputs: findings.jsonl and summary.csv.

The summary.csv columns are designed to be human-skimmable AND a superset of
the metadata produced by the sibling PDFScraper tool, so its consumers can
swap in this output without losing context.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from pdf_a11y.models import BatchReport


def write_findings_jsonl(batch: BatchReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as fh:
        for report in batch.reports:
            base = {
                "source": report.metadata.source,
                "final_url": report.metadata.final_url,
                "sha256": report.metadata.sha256,
                "score_pct": report.score.score_pct,
                "grade": report.score.grade,
                "critical_fail": report.score.critical_fail,
            }
            for f in report.findings:
                row = {
                    **base,
                    "check_id": f.check_id,
                    "severity": f.severity.value,
                    "category": f.category.value,
                    "detection": f.detection.value,
                    "message": f.message,
                    "page": f.page,
                    "location": f.location,
                    "remediation": f.remediation,
                    "standards": [f"{s.standard.value} §{s.clause}" for s in f.standards],
                    "requires_manual_verification": f.requires_manual_verification,
                    "evidence": f.evidence,
                }
                fh.write(json.dumps(row, ensure_ascii=False, default=str) + "\n")


# Column order chosen to feel familiar to anyone who used the sibling
# PDFScraper CSV — its columns appear first, then accessibility scoring,
# then severity counts, then critical-fail reasons, then any user-passed
# metadata columns from the input CSV.
_FIXED_COLUMNS: list[tuple[str, str]] = [
    ("PDF URL", "source"),
    ("PDF URL Status", "_http_status"),
    ("Final URL", "final_url"),
    ("Unique Hash", "sha256"),
    ("Duplicate PDF", "_is_duplicate"),
    ("Uses AcroForm", "_has_acroform"),
    ("Uses XFA Form", "_has_xfa"),
    ("Has Fillable Form", "_has_fillable_form"),
    ("PDF Format Version", "pdf_version"),
    ("PDF Size (MB)", "_byte_size_mb"),
    ("Creator", "creator"),
    ("Producer", "producer"),
    ("Total PDF Pages", "page_count"),
    ("Creation Date", "creation_date"),
    ("Last Modified Date", "modification_date"),
    ("Days between Created and Modified", "days_between_created_modified"),
    ("Days Since Last Modified", "days_since_modified"),
    ("Document Title", "title"),
    ("Document Language", "language"),
    ("Has Bookmarks", "_has_bookmarks"),
    ("Tagged PDF", "_tagged"),
    ("Encrypted", "_encrypted"),
    ("Encryption Blocks AT", "_encryption_blocks_at"),
    ("Claims PDF/UA", "_claims_pdf_ua"),
    ("Accessibility Score", "_score_pct"),
    ("Accessibility Grade", "_grade"),
    ("Critical Fail", "_critical_fail"),
    ("Critical Fail Reasons", "_critical_fail_reasons"),
    ("# Critical Findings", "_n_critical"),
    ("# Major Findings", "_n_major"),
    ("# Minor Findings", "_n_minor"),
    ("# Warning Findings", "_n_warning"),
    ("Top Issues", "_top_issues"),
    ("Error", "error"),
]


def _row_for(report) -> dict[str, object]:  # type: ignore[no-untyped-def]
    m = report.metadata
    s = report.score
    counts = {"Critical": 0, "Major": 0, "Minor": 0, "Warning": 0}
    for f in report.findings:
        counts[f.severity.value] += 1
    top = ", ".join(f.check_id for f in report.top_findings) or ""

    raw: dict[str, object] = {
        "_http_status": m.http_status if m.http_status is not None else "",
        "_is_duplicate": _bool_str(m.is_duplicate),
        "_has_acroform": _bool_str(m.has_acroform),
        "_has_xfa": _bool_str(m.has_xfa),
        "_has_fillable_form": _bool_str(m.has_fillable_form),
        "_byte_size_mb": m.byte_size_mb,
        "_has_bookmarks": _bool_str(m.has_bookmarks),
        "_tagged": _bool_str(m.has_tagged_structure),
        "_encrypted": _bool_str(m.encrypted),
        "_encryption_blocks_at": _bool_str(m.encryption_blocks_at),
        "_claims_pdf_ua": _bool_str(m.claims_pdf_ua),
        "_score_pct": s.score_pct,
        "_grade": s.grade,
        "_critical_fail": _bool_str(s.critical_fail),
        "_critical_fail_reasons": ",".join(s.critical_fail_reasons),
        "_n_critical": counts["Critical"],
        "_n_major": counts["Major"],
        "_n_minor": counts["Minor"],
        "_n_warning": counts["Warning"],
        "_top_issues": top,
    }
    out: dict[str, object] = {}
    for header, key in _FIXED_COLUMNS:
        if key.startswith("_"):
            out[header] = raw.get(key, "")
        else:
            out[header] = (
                getattr(m, key, None)
                if hasattr(m, key)
                else (getattr(s, key, "") if hasattr(s, key) else getattr(report, key, ""))
            )
            if out[header] is None:
                out[header] = ""
    return out


def _bool_str(v: object) -> str:
    if v is None:
        return ""
    return "TRUE" if bool(v) else "FALSE"


def write_summary_csv(batch: BatchReport, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)

    extra_user_fields: list[str] = []
    for r in batch.reports:
        for k in r.user_metadata:
            if k not in extra_user_fields:
                extra_user_fields.append(k)

    headers = [h for h, _ in _FIXED_COLUMNS] + [f"meta:{k}" for k in extra_user_fields]
    with path.open("w", encoding="utf-8", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=headers)
        writer.writeheader()
        for r in batch.reports:
            row = _row_for(r)
            for k in extra_user_fields:
                row[f"meta:{k}"] = r.user_metadata.get(k, "")
            writer.writerow(row)
