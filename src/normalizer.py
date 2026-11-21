"""Core pure-Python normalization, deterministic PII redaction, chunking, and deduplication."""

from __future__ import annotations

import csv
import hashlib
import io
import json
import math
import re
import unicodedata
from dataclasses import dataclass
from typing import Any


PII_PATTERNS: list[tuple[str, re.Pattern[str], str]] = [
    (
        "email",
        re.compile(r"\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}\b"),
        "[REDACTED_EMAIL]",
    ),
    (
        "api_token",
        re.compile(
            r"\b(?:sk-[A-Za-z0-9_-]{16,}|gh[pousr]_[A-Za-z0-9]{20,}|AKIA[0-9A-Z]{16}|AIza[0-9A-Za-z_-]{30,})\b"
        ),
        "[REDACTED_TOKEN]",
    ),
    (
        "credit_card",
        re.compile(r"(?<!\d)(?:\d{4}[-\s]?){3}\d{4}(?!\d)"),
        "[REDACTED_CARD]",
    ),
    (
        "phone",
        re.compile(
            r"(?<!\d)(?:\+?\d{1,3}[-\s]?)?(?:\(0?\d{1,4}\)|0\d{1,4})[-\s]?\d{1,4}[-\s]?\d{3,4}(?!\d)"
        ),
        "[REDACTED_PHONE]",
    ),
    (
        "ipv4",
        re.compile(
            r"\b(?:(?:25[0-5]|2[0-4]\d|1?\d?\d)\.){3}(?:25[0-5]|2[0-4]\d|1?\d?\d)\b"
        ),
        "[REDACTED_IP]",
    ),
]


@dataclass(frozen=True)
class NormalizedChunk:
    document_id: str
    chunk_index: int
    heading: str
    text: str
    char_count: int
    estimated_tokens: int
    sha256: str
    pii_redactions: dict[str, int]
    metadata: dict[str, Any]

    def to_dict(self) -> dict[str, Any]:
        return {
            "documentId": self.document_id,
            "chunkIndex": self.chunk_index,
            "heading": self.heading,
            "text": self.text,
            "charCount": self.char_count,
            "estimatedTokens": self.estimated_tokens,
            "sha256": self.sha256,
            "piiRedactions": self.pii_redactions,
            "metadata": self.metadata,
        }


def normalize_whitespace(text: str) -> str:
    text = unicodedata.normalize("NFKC", text)
    text = text.replace("\r\n", "\n").replace("\r", "\n")
    lines = [re.sub(r"[ \t]+", " ", ln).strip() for ln in text.split("\n")]
    collapsed = "\n".join(lines)
    return re.sub(r"\n{3,}", "\n\n", collapsed).strip()


def redact_pii(text: str) -> tuple[str, dict[str, int]]:
    counts: dict[str, int] = {}
    out = text
    for name, pattern, replacement in PII_PATTERNS:
        out, n = pattern.subn(replacement, out)
        if n > 0:
            counts[name] = n
    return out, counts


def estimate_tokens(text: str) -> int:
    """Heuristic token estimate handling both ASCII and CJK characters."""
    if not text:
        return 0
    ascii_chars = sum(1 for ch in text if ord(ch) < 128)
    non_ascii_chars = len(text) - ascii_chars
    return max(1, math.ceil(ascii_chars / 4 + non_ascii_chars * 1.1))


def convert_to_text(content: str, fmt: str) -> str:
    fmt_norm = (fmt or "text").strip().lower()
    if fmt_norm == "csv":
        reader = csv.DictReader(io.StringIO(content))
        if not reader.fieldnames:
            return normalize_whitespace(content)
        lines: list[str] = []
        for idx, row in enumerate(reader, start=1):
            parts = [
                f"{(k or '').strip()}: {(v or '').strip()}"
                for k, v in row.items()
                if k is not None and (v or "").strip()
            ]
            if parts:
                lines.append(f"Row {idx} | " + " | ".join(parts))
        return "\n".join(lines)

    if fmt_norm == "json":
        parsed = json.loads(content)
        return _flatten_json(parsed)

    return content


def _flatten_json(obj: Any, prefix: str = "") -> str:
    lines: list[str] = []
    if isinstance(obj, dict):
        for k, v in obj.items():
            key = f"{prefix}.{k}" if prefix else str(k)
            if isinstance(v, (dict, list)):
                sub = _flatten_json(v, key)
                if sub:
                    lines.append(sub)
            elif v is not None:
                lines.append(f"{key}: {v}")
    elif isinstance(obj, list):
        for i, item in enumerate(obj):
            key = f"{prefix}[{i}]"
            if isinstance(item, (dict, list)):
                sub = _flatten_json(item, key)
                if sub:
                    lines.append(sub)
            elif item is not None:
                lines.append(f"{key}: {item}")
    elif obj is not None:
        lines.append(f"{prefix}: {obj}" if prefix else str(obj))
    return "\n".join(lines)


def split_markdown_sections(text: str) -> list[tuple[str, str]]:
    """Split text by Markdown headings while preserving heading context."""
    sections: list[tuple[str, list[str]]] = []
    current_heading = ""
    current_lines: list[str] = []

    for line in text.split("\n"):
        m = re.match(r"^(#{1,6})\s+(.+)$", line)
        if m:
            if current_lines:
                sections.append((current_heading, current_lines))
            current_heading = m.group(2).strip()
            current_lines = [line]
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, current_lines))

    return [(h, "\n".join(ls).strip()) for h, ls in sections if "\n".join(ls).strip()]


def chunk_text(text: str, chunk_size: int, chunk_overlap: int) -> list[str]:
    if chunk_size < 1:
        raise ValueError("chunk_size must be positive")
    if chunk_overlap < 0 or chunk_overlap >= chunk_size:
        raise ValueError("chunk_overlap must be >= 0 and < chunk_size")
    if len(text) <= chunk_size:
        return [text]

    chunks: list[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + chunk_size, n)
        if end < n:
            split_at = text.rfind("\n\n", start + chunk_size // 2, end)
            if split_at == -1:
                split_at = text.rfind("\n", start + chunk_size // 2, end)
            if split_at == -1:
                split_at = text.rfind(" ", start + chunk_size // 2, end)
            if split_at != -1 and split_at > start:
                end = split_at
        piece = text[start:end].strip()
        if piece:
            chunks.append(piece)
        if end >= n:
            break
        next_start = max(start + 1, end - chunk_overlap)
        start = next_start
    return chunks


def process_documents(
    documents: list[dict[str, Any]],
    *,
    chunk_size: int = 800,
    chunk_overlap: int = 100,
    do_redact_pii: bool = True,
    deduplicate: bool = True,
) -> tuple[list[NormalizedChunk], dict[str, Any]]:
    if not isinstance(documents, list):
        raise ValueError("documents must be a list")

    seen_hashes: set[str] = set()
    output: list[NormalizedChunk] = []
    duplicates_skipped = 0
    total_pii_redactions: dict[str, int] = {}

    for idx, doc in enumerate(documents):
        if not isinstance(doc, dict):
            continue
        doc_id = str(doc.get("id") or f"doc-{idx + 1}")
        fmt = str(doc.get("format") or "text")
        raw_content = doc.get("content")
        if not isinstance(raw_content, str) or not raw_content.strip():
            continue
        metadata = doc.get("metadata") if isinstance(doc.get("metadata"), dict) else {}

        converted = convert_to_text(raw_content, fmt)
        normalized = normalize_whitespace(converted)
        if not normalized:
            continue

        sections = (
            split_markdown_sections(normalized)
            if fmt.strip().lower() == "markdown"
            else [("", normalized)]
        )

        chunk_idx = 0
        for heading, section_text in sections:
            for piece in chunk_text(section_text, chunk_size, chunk_overlap):
                if do_redact_pii:
                    cleaned_piece, redactions = redact_pii(piece)
                else:
                    cleaned_piece, redactions = piece, {}

                digest = hashlib.sha256(cleaned_piece.encode("utf-8")).hexdigest()
                if deduplicate and digest in seen_hashes:
                    duplicates_skipped += 1
                    continue
                seen_hashes.add(digest)

                for k, v in redactions.items():
                    total_pii_redactions[k] = total_pii_redactions.get(k, 0) + v

                output.append(
                    NormalizedChunk(
                        document_id=doc_id,
                        chunk_index=chunk_idx,
                        heading=heading,
                        text=cleaned_piece,
                        char_count=len(cleaned_piece),
                        estimated_tokens=estimate_tokens(cleaned_piece),
                        sha256=digest,
                        pii_redactions=redactions,
                        metadata=metadata,
                    )
                )
                chunk_idx += 1

    stats = {
        "inputDocuments": len(documents),
        "outputChunks": len(output),
        "duplicatesSkipped": duplicates_skipped,
        "piiRedactions": total_pii_redactions,
    }
    return output, stats
