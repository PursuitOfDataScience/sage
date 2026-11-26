"""Text out of a scanned PDF, asked of a gateway's PDF parser, when the PDF has none.

`files.process` extracts a PDF's text layer locally, and a scanned PDF has none: the
reader is told "No text found ... Scanned PDFs need OCR before upload." This module is
the one step past that, for a deployment that switches it on: the PDF goes to a
provider that parses files (OpenRouter's `file-parser` plugin), and the text it
extracted is read back off the response's file annotation, so whichever model then
answers the question (Vertex included) gets text, exactly as for a PDF that had a text
layer to begin with.

Off unless `config.PDF_OCR` names a `provider:model` to send the parse through, and
safe by construction when on: every failure (no key, a refusal, a timeout, an answer
with no annotation) leaves the reader with the message they get today. Two things to
decide before switching it on, both the operator's:

* **Where the file goes.** A scanned PDF leaves for the gateway and, behind it, the
  parsing engine (`config.PDF_OCR_ENGINE`: `cloudflare-ai` is free and Cloudflare's,
  `mistral-ocr` is $2 per 1000 pages and Mistral's), even when the model answering is
  not there.
* **The balance.** OpenRouter refuses any request carrying a file unless the account
  holds at least $0.50 (measured 2026-11-26: `402 ... requires at least $0.50 in balance
  for files`), so on an account below that this does nothing but fail safe.
"""

from __future__ import annotations

import base64
import logging

from . import config, env, files
from .profile import active as _active

logger = logging.getLogger(__name__)


def _is_pdf(filename: str, data: bytes) -> bool:
    return data.startswith(b"%PDF") or filename.lower().endswith(".pdf")


def parsed_text(response: dict) -> str:
    """The text a file-parser annotation carries, without its `<file>` wrapper."""
    try:
        message = (response.get("choices") or [{}])[0].get("message") or {}
        parts = []
        for note in message.get("annotations") or ():
            if not isinstance(note, dict) or note.get("type") != "file":
                continue
            for part in (note.get("file") or {}).get("content") or ():
                text = part.get("text") if isinstance(part, dict) else None
                if not isinstance(text, str):
                    continue
                stripped = text.strip()
                if stripped.startswith("<file name=") or stripped == "</file>":
                    continue
                parts.append(text)
        return "\n".join(parts).strip()
    except Exception:  # noqa: BLE001 (an unreadable answer is no text)
        return ""


def read_scanned(filename: str, data: bytes) -> str:
    """The PDF's text as the configured provider's parser reads it, or "" on any failure."""
    target = config.PDF_OCR
    if ":" not in target:
        return ""
    name, model = target.split(":", 1)
    entry = _active().provider(name)
    key = env.text(entry.key_env) if entry and entry.key_env else ""
    if not (entry and entry.base_url and key and model):
        logger.warning("PDF OCR is set to %s, which is not a keyed provider", target)
        return ""
    body = {
        "model": model,
        # The model is asked for nothing: the plugin parses the file before the model
        # sees it, and what is wanted is the annotation, not an answer.
        "max_tokens": 1,
        "messages": [{"role": "user", "content": [
            {"type": "text", "text": "Reply with the single word OK."},
            {"type": "file", "file": {
                "filename": files.safe_filename(filename),
                "file_data": "data:application/pdf;base64,"
                + base64.b64encode(data).decode("ascii"),
            }},
        ]}],
        "plugins": [{"id": "file-parser", "pdf": {"engine": config.PDF_OCR_ENGINE}}],
    }
    try:
        import httpx  # noqa: PLC0415

        response = httpx.post(
            f"{entry.base_url.rstrip('/')}/chat/completions", json=body, timeout=90,
            headers={"Authorization": f"Bearer {key}"},
        )
        response.raise_for_status()
        return parsed_text(response.json())
    except Exception as exc:  # noqa: BLE001 (the reader keeps today's message)
        logger.warning("PDF OCR of %s failed: %s", files.safe_filename(filename), exc)
        return ""


def process(filename: str, data: bytes):
    """`files.process`, with one more try for a PDF whose text layer is empty.

    Returns exactly what `files.process` returns in every other case, including every
    case where the OCR step is off or fails, so switching it off is switching it off.
    """
    attachment, error = files.process(filename, data)
    if attachment is not None or not config.PDF_OCR or not _is_pdf(filename, data):
        return attachment, error
    if len(data) > config.MAX_UPLOAD_BYTES:
        return attachment, error
    try:
        # The same extraction `files.process` ran: OCR is only for a PDF that opened
        # and had no text in it, not for one that is corrupt or encrypted.
        text, pages = files._extract_pdf(data)  # noqa: SLF001 (same package)
    except Exception:  # noqa: BLE001
        return attachment, error
    if text.strip():
        return attachment, error
    scanned = read_scanned(filename, data)
    if not scanned:
        return attachment, error
    clipped, truncated = files._truncate(scanned, "Document")  # noqa: SLF001
    logger.info("Read %s through PDF OCR: %d characters", files.safe_filename(filename),
                len(scanned))
    return files.Attachment(files.safe_filename(filename), "pdf", clipped, pages,
                            truncated), None
