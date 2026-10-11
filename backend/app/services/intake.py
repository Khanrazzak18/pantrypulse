"""Donation intake: check an upload, build the model's input, and read items out of it."""

from __future__ import annotations

import email
import email.policy
import html
import io
import logging
import os
import re
from dataclasses import dataclass
from datetime import date
from html.parser import HTMLParser
from typing import BinaryIO

from PIL import Image
from pydantic import ValidationError

from app.ai.llm_provider import (
    InvalidModelOutput,
    LLMAccessDenied,
    LLMBadRequest,
    LLMNotConfigured,
    LLMProvider,
    LLMResult,
    LLMThrottled,
    LLMTimeout,
    LLMUnavailable,
    run_with_retry,
)
from app.ai.prompts import load_prompt
from app.errors import ApiError
from app.schemas.intake import DonationExtraction, tool_input_schema
from app.schemas.types import scrub

logger = logging.getLogger("pantrypulse.intake")

MB = 1024 * 1024
MAX_UPLOAD_BYTES = 10 * MB
# Bedrock Converse limits for bytes sent inline (checked against the live API in Stage 4).
MAX_PDF_BYTES = int(4.5 * MB)
MAX_IMAGE_BYTES = int(3.75 * MB)
MAX_TEXT_CHARS = 100_000

TOOL_NAME = "record_donation_items"
TOOL_DESCRIPTION = "Record every donated food item found in the manifest."
ALLOWED_TYPES_TEXT = "PDF, PNG, JPG, WEBP, TXT or EML"

# extension -> (kind, content type)
ALLOWED_EXTENSIONS = {
    ".pdf": ("pdf", "application/pdf"),
    ".png": ("image", "image/png"),
    ".jpg": ("image", "image/jpeg"),
    ".jpeg": ("image", "image/jpeg"),
    ".webp": ("image", "image/webp"),
    ".txt": ("text", "text/plain"),
    ".eml": ("email", "message/rfc822"),
}
_IMAGE_FORMATS = {".png": "png", ".jpg": "jpeg", ".jpeg": "jpeg", ".webp": "webp"}
_SHRINK_STEPS = (2000, 1600, 1280, 1024, 800)


@dataclass
class PreparedUpload:
    filename: str
    ext: str
    kind: str  # pdf | image | text | email
    content_type: str
    data: bytes  # exactly what was uploaded (this is what gets stored)
    text: str | None = None
    model_bytes: bytes | None = None  # image bytes sent to the model (possibly shrunk)
    model_format: str | None = None

    @property
    def source_type(self) -> str:
        return self.kind


# --- file checks -----------------------------------------------------------------------------


def clean_filename(raw: str) -> str:
    """A safe name for display only. Stored files are named by a random key, never by this."""
    name = raw.replace("\\", "/").split("/")[-1]
    name = re.sub(r"[\x00-\x1f\x7f]", "", name).strip()
    if len(name) > 255:
        stem, ext = os.path.splitext(name)
        name = stem[: 255 - len(ext)] + ext
    return name or "upload"


def _mb(size: int) -> str:
    return f"{size / MB:.1f} MB"


def read_limited(handle: BinaryIO, declared_size: int | None) -> bytes:
    """Read an upload, refusing anything over 10 MB."""
    data = handle.read(MAX_UPLOAD_BYTES + 1)
    if len(data) > MAX_UPLOAD_BYTES:
        size = declared_size if declared_size and declared_size > MAX_UPLOAD_BYTES else None
        detail = f"This file is {_mb(size)}" if size else "This file is larger than 10 MB"
        raise ApiError(413, "file_too_large", f"{detail}. The limit is 10 MB.")
    return data


def _invalid(name: str, what: str) -> ApiError:
    return ApiError(415, "invalid_file_content", f"'{name}' isn't a valid {what} file.")


def _check_magic(name: str, ext: str, data: bytes) -> None:
    if ext == ".pdf" and not data.startswith(b"%PDF-"):
        raise _invalid(name, "PDF")
    if ext == ".png" and not data.startswith(b"\x89PNG\r\n\x1a\n"):
        raise _invalid(name, "PNG")
    if ext in (".jpg", ".jpeg") and not data.startswith(b"\xff\xd8\xff"):
        raise _invalid(name, "JPG")
    if ext == ".webp" and not (data[:4] == b"RIFF" and data[8:12] == b"WEBP"):
        raise _invalid(name, "WEBP")


def _open_image(name: str, ext: str, data: bytes) -> Image.Image:
    try:
        image = Image.open(io.BytesIO(data))
        image.load()  # decode fully: catches truncated and corrupt files
        return image
    except Image.DecompressionBombError as exc:
        raise ApiError(413, "file_too_large", f"The image '{name}' has too many pixels.") from exc
    except (OSError, SyntaxError, ValueError) as exc:
        raise _invalid(name, ext.lstrip(".").upper()) from exc


def _shrink(image: Image.Image) -> bytes | None:
    """Re-encode as JPEG, shrinking until it fits the model's inline image limit."""
    if image.mode in ("RGBA", "LA", "P"):
        rgba = image.convert("RGBA")
        flat = Image.new("RGB", rgba.size, "white")
        flat.paste(rgba, mask=rgba.split()[-1])
        image = flat
    else:
        image = image.convert("RGB")
    for longest in _SHRINK_STEPS:
        candidate = image.copy()
        candidate.thumbnail((longest, longest))
        out = io.BytesIO()
        candidate.save(out, "JPEG", quality=85)
        if out.tell() <= MAX_IMAGE_BYTES:
            return out.getvalue()
    return None


class _TextExtractor(HTMLParser):
    _BREAKS = {"br", "p", "div", "tr", "li", "h1", "h2", "h3", "h4", "table"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.parts: list[str] = []
        self._skip = 0

    def handle_starttag(self, tag, attrs):
        if tag in ("script", "style"):
            self._skip += 1
        elif tag in self._BREAKS:
            self.parts.append("\n")
        elif tag in ("td", "th"):
            self.parts.append(" | ")

    def handle_endtag(self, tag):
        if tag in ("script", "style"):
            self._skip = max(0, self._skip - 1)
        elif tag in self._BREAKS:
            self.parts.append("\n")

    def handle_data(self, data):
        if not self._skip:
            self.parts.append(data)


def _html_to_text(markup: str) -> str:
    parser = _TextExtractor()
    parser.feed(markup)
    text = html.unescape("".join(parser.parts))
    return "\n".join(line.strip() for line in text.splitlines() if line.strip())


def _eml_to_text(data: bytes) -> str:
    message = email.message_from_bytes(data, policy=email.policy.default)
    lines = [f"{h}: {message[h]}" for h in ("From", "To", "Subject", "Date") if message[h]]
    body = message.get_body(preferencelist=("plain", "html"))
    text = ""
    if body is not None:
        content = body.get_content()
        text = _html_to_text(content) if body.get_content_type() == "text/html" else content
    attachments = [a.get_filename() or "unnamed" for a in message.iter_attachments()]
    out = "\n".join(lines) + "\n\n" + text.strip()
    if attachments:
        out += f"\n\n[Attachments (names only, not read): {', '.join(attachments)}]"
    return out.strip()


def _decode_text(name: str, data: bytes) -> str:
    if b"\x00" in data:
        raise _invalid(name, "text")
    try:
        return data.decode("utf-8-sig")
    except UnicodeDecodeError:
        try:
            return data.decode("cp1252")
        except UnicodeDecodeError as exc:
            raise _invalid(name, "text") from exc


def prepare_upload(filename: str, data: bytes) -> PreparedUpload:
    """Check type, content and size. Raises ApiError with a message a coordinator can act on."""
    name = clean_filename(filename)
    ext = os.path.splitext(name)[1].lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise ApiError(
            415,
            "unsupported_file_type",
            f"'{name}' can't be used. Upload a {ALLOWED_TYPES_TEXT} file.",
        )
    if not data.strip():
        raise ApiError(422, "empty_file", f"'{name}' is empty.")
    kind, content_type = ALLOWED_EXTENSIONS[ext]
    prepared = PreparedUpload(name, ext, kind, content_type, data)

    if kind in ("pdf", "image"):
        _check_magic(name, ext, data)
    if kind == "pdf":
        if len(data) > MAX_PDF_BYTES:
            raise ApiError(
                413,
                "file_too_large_for_ai",
                f"This PDF is {_mb(len(data))}. The AI can read PDFs up to 4.5 MB. "
                "Try a smaller or compressed copy.",
            )
    elif kind == "image":
        image = _open_image(name, ext, data)
        if len(data) <= MAX_IMAGE_BYTES:
            prepared.model_bytes, prepared.model_format = data, _IMAGE_FORMATS[ext]
        else:
            shrunk = _shrink(image)
            if shrunk is None:
                raise ApiError(
                    413,
                    "file_too_large_for_ai",
                    f"This image is too large for the AI to read ({_mb(len(data))}). "
                    "Try a smaller photo.",
                )
            prepared.model_bytes, prepared.model_format = shrunk, "jpeg"
    else:
        text = _decode_text(name, data)
        if kind == "email":
            text = _eml_to_text(data)
        if len(text) > MAX_TEXT_CHARS:
            raise ApiError(
                413,
                "file_too_large",
                f"'{name}' has more than {MAX_TEXT_CHARS:,} characters, which is too long to read.",
            )
        if not text.strip():
            raise ApiError(422, "empty_file", f"'{name}' is empty.")
        prepared.text = text
    return prepared


# --- the model's input -----------------------------------------------------------------------


def build_content(prepared: PreparedUpload, today: date) -> list[dict]:
    instruction = {
        "text": (
            f"Today's date is {today.isoformat()}. Record every donated item in the manifest "
            f"by calling the {TOOL_NAME} tool."
        )
    }
    if prepared.kind == "pdf":
        document = {"format": "pdf", "name": "manifest", "source": {"bytes": prepared.data}}
        return [{"document": document}, instruction]
    if prepared.kind == "image":
        image = {"format": prepared.model_format, "source": {"bytes": prepared.model_bytes}}
        return [{"image": image}, instruction]
    # Text is untrusted: delimit it, and stop it from closing the delimiter early.
    safe = (prepared.text or "").replace("</manifest>", "< /manifest>")
    return [{"text": f"<manifest>\n{safe}\n</manifest>"}, instruction]


# --- extraction ------------------------------------------------------------------------------


@dataclass
class ExtractionOutcome:
    extraction: DonationExtraction
    raw: dict  # what is stored as JSONB on the donation
    result: LLMResult
    attempts: int
    input_tokens: int
    output_tokens: int


def _summarise(error: ValidationError) -> str:
    parts = [f"{'.'.join(str(p) for p in e['loc'])}: {e['msg']}" for e in error.errors()[:5]]
    return "; ".join(parts)[:500]


def parse_result(result: LLMResult) -> DonationExtraction:
    if result.tool_input is None:
        raise InvalidModelOutput(f"you did not call the {TOOL_NAME} tool")
    try:
        return DonationExtraction.model_validate(result.tool_input)
    except ValidationError as exc:
        raise InvalidModelOutput(_summarise(exc)) from exc


def extract_items(llm: LLMProvider, prepared: PreparedUpload, today: date) -> ExtractionOutcome:
    system = load_prompt("extract_donation")
    schema = tool_input_schema()
    content = build_content(prepared, today)

    def call(hint: str | None) -> LLMResult:
        blocks = content if hint is None else [*content, {"text": hint}]
        return llm.converse_tool(
            system=system,
            content=blocks,
            tool_name=TOOL_NAME,
            tool_description=TOOL_DESCRIPTION,
            input_schema=schema,
        )

    try:
        outcome = run_with_retry(call, parse_result)
    except InvalidModelOutput as exc:
        raise ApiError(
            502,
            "ai_invalid_output",
            "The AI couldn't read this file into a usable list after two tries. "
            "Please try again, or use a clearer copy of the file.",
        ) from exc
    except LLMTimeout as exc:
        raise ApiError(
            504, "ai_timeout", "The AI took too long to read this file. Please try again."
        ) from exc
    except LLMThrottled as exc:
        raise ApiError(
            503, "ai_busy", "The AI service is busy right now. Please try again in a minute."
        ) from exc
    except LLMNotConfigured as exc:
        raise ApiError(
            503,
            "ai_not_configured",
            "AI intake isn't set up yet. Ask an administrator to set BEDROCK_MODEL_ID.",
        ) from exc
    except (LLMAccessDenied, LLMBadRequest, LLMUnavailable) as exc:
        raise ApiError(
            502,
            "ai_unavailable",
            "The AI service isn't available right now. Please try again, or ask an "
            "administrator to check the Bedrock setup.",
        ) from exc

    extraction = outcome.value
    if not extraction.items:
        raise ApiError(
            422,
            "no_items_found",
            "We couldn't find any donation items in this file. Check that it's the right manifest.",
            {"notes": extraction.notes},
        )
    raw = scrub(
        {
            "tool_input": outcome.result.tool_input,
            "parsed": extraction.model_dump(mode="json"),
            "usage": {"input_tokens": outcome.input_tokens, "output_tokens": outcome.output_tokens},
            "attempts": outcome.attempts,
        }
    )
    logger.info(
        "donation_extracted",
        extra={
            "items": len(extraction.items),
            "attempts": outcome.attempts,
            "input_tokens": outcome.input_tokens,
            "output_tokens": outcome.output_tokens,
            "kind": prepared.kind,
        },
    )
    return ExtractionOutcome(
        extraction,
        raw,
        outcome.result,
        outcome.attempts,
        outcome.input_tokens,
        outcome.output_tokens,
    )
