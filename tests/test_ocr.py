"""`sage.ocr`: a scanned PDF gets one more try, and only a scanned PDF.

Built offline: a two-page image-only PDF (no text layer, as a scan has) and a stand-in
for httpx answering with the annotation shape OpenRouter documents. Off, `ocr.process`
must be `files.process` exactly, and on, every failure must leave the reader with the
message they get today.
"""

from __future__ import annotations

import io
import sys
from types import ModuleType

import pytest

from sage import config, files, ocr
from sage.profile import from_mapping

pypdf = pytest.importorskip("pypdf")


def scanned_pdf() -> bytes:
    """Two blank pages: a PDF that opens and has no text layer."""
    writer = pypdf.PdfWriter()
    writer.add_blank_page(width=612, height=792)
    writer.add_blank_page(width=612, height=792)
    buffer = io.BytesIO()
    writer.write(buffer)
    return buffer.getvalue()


ANNOTATED = {"choices": [{"message": {"content": "OK", "annotations": [{
    "type": "file",
    "file": {"hash": "abc", "name": "scan.pdf", "content": [
        {"type": "text", "text": '<file name="scan.pdf">'},
        {"type": "text", "text": "#SBATCH --partition=caslake"},
        {"type": "image_url", "image_url": {"url": "data:image/png;base64,AAAA"}},
        {"type": "text", "text": "slurmstepd: error: Detected 1 oom-kill event"},
        {"type": "text", "text": "</file>"},
    ]},
}]}}]}


@pytest.fixture
def gateway(monkeypatch):
    """A keyed provider in the profile, and a stand-in for its HTTP endpoint."""
    from sage import profile as profile_module

    declared = from_mapping({"providers": [{
        "name": "gw", "base_url": "https://gw.test/api/v1", "key_env": "GW_TEST_KEY",
    }]})
    monkeypatch.setattr(profile_module, "_active", declared)
    monkeypatch.setenv("GW_TEST_KEY", "k")
    monkeypatch.setattr(config, "PDF_OCR", "gw:vendor/cheap-model")
    sent = []
    state = {"answer": ANNOTATED}

    class Response:
        def raise_for_status(self):
            if isinstance(state["answer"], Exception):
                raise state["answer"]

        def json(self):
            return state["answer"]

    def post(url, json=None, headers=None, timeout=None):
        sent.append({"url": url, "json": json})
        return Response()

    fake = ModuleType("httpx")
    fake.post = post
    monkeypatch.setitem(sys.modules, "httpx", fake)
    return sent, state


def test_off_it_is_files_process_exactly(monkeypatch):
    monkeypatch.setattr(config, "PDF_OCR", "")
    data = scanned_pdf()
    assert ocr.process("scan.pdf", data) == files.process("scan.pdf", data)
    assert ocr.process("scan.pdf", data)[1].startswith("No text found in scan.pdf")


def test_a_scanned_pdf_is_read_through_the_parser(gateway):
    sent, _state = gateway
    attachment, error = ocr.process("scan.pdf", scanned_pdf())
    assert error is None
    assert attachment.kind == "pdf" and attachment.pages == 2
    assert attachment.text == (
        "#SBATCH --partition=caslake\nslurmstepd: error: Detected 1 oom-kill event"
    )
    (request,) = sent
    assert request["url"] == "https://gw.test/api/v1/chat/completions"
    assert request["json"]["model"] == "vendor/cheap-model"
    assert request["json"]["plugins"] == [{"id": "file-parser",
                                           "pdf": {"engine": config.PDF_OCR_ENGINE}}]
    assert request["json"]["max_tokens"] == 1


@pytest.mark.parametrize("answer", [
    RuntimeError("HTTP 402: requires at least $0.50 in balance for files"),
    {"choices": [{"message": {"content": "OK"}}]},
    {"choices": []},
    {"choices": [{"message": {"annotations": [{"type": "file", "file": {"content": [
        {"type": "text", "text": '<file name="scan.pdf">'},
        {"type": "text", "text": "</file>"}]}}]}}]},
])
def test_every_failure_keeps_todays_message(gateway, answer):
    _sent, state = gateway
    state["answer"] = answer
    attachment, error = ocr.process("scan.pdf", scanned_pdf())
    assert attachment is None
    assert error.startswith("No text found in scan.pdf")


def test_a_pdf_with_text_is_never_sent(gateway):
    sent, _state = gateway
    attachment, error = ocr.process("notes.txt", b"plain text, not a pdf")
    assert error is None and attachment.kind == "text"
    assert sent == []


def test_a_provider_without_a_key_is_never_asked(gateway, monkeypatch):
    sent, _state = gateway
    monkeypatch.delenv("GW_TEST_KEY")
    _attachment, error = ocr.process("scan.pdf", scanned_pdf())
    assert error.startswith("No text found")
    assert sent == []


def test_a_malformed_setting_is_off(gateway, monkeypatch):
    sent, _state = gateway
    monkeypatch.setattr(config, "PDF_OCR", "no-colon-here")
    _attachment, error = ocr.process("scan.pdf", scanned_pdf())
    assert error.startswith("No text found")
    assert sent == []
