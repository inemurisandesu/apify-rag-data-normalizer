# RAG & LLM Data Normalizer (Apify Actor)

100% non-scraping utility Actor for AI agents, MCP pipelines, and RAG ingestion workflows.

## What It Does
- **Multi-format input normalization**: Converts caller-supplied `text`, `markdown`, `csv`, and `json` into clean, NFKC-normalized text.
- **Deterministic PII & Secret Redaction**: Masks email addresses, phone numbers, IPv4 addresses, card-like numbers, and common API token formats (`sk-...`, `ghp_...`, `AKIA...`, `AIza...`) with per-chunk audit counts.
- **Heading-Aware Chunking & Token Estimation**: Splits long Markdown/text into configurable chunks with overlap and CJK-aware token estimation.
- **SHA-256 Deduplication**: Automatically drops identical normalized chunks across documents.
- **Pay-Per-Event Ready**: Emits dataset items using `charged_event_name="normalized-chunk"` for transparent Apify Store PPE billing.

## Security & Compliance
- **Zero web scraping / zero external network calls**: Processes only caller-supplied data.
- **Minimal dependencies**: Python standard library + official `apify` SDK only.

## Local Verification
```bash
python3 -m unittest discover -s tests -v
```
