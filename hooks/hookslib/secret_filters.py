"""Narrow, detector-specific exclusions for noncredential vault content.

Never exclude whole documentation/test files or generic token assignments.
Weak example passwords remain auditable because they can also be real passwords.
"""

from __future__ import annotations

import base64
import binascii
import re
from dataclasses import dataclass
from email import policy
from email.parser import BytesParser
from functools import lru_cache
from pathlib import Path
from typing import cast

ENTROPY_TYPES = frozenset({"Hex High Entropy String", "Base64 High Entropy String"})
PLACEHOLDER = re.compile(
    r"(?:<[_a-zA-Z][\w -]*>|"
    r"(?:[a-z]+[_-])?your[_-](?:api[_-])?(?:key|token|password)(?:[_-]here)?|"
    r"(?:sk|comfyui)[_-](?:\.{3}|x{6,})|"
    r"generate-a-strong-secret-here)"
)
QUOTED_FIELD = re.compile(r"""["']?(?P<key>[\w:]+)["']?\s*[:=]\s*["'](?P<value>[^"']*)["']""")


@dataclass(frozen=True)
class Candidate:
    value: str
    line: str
    kind: str
    filename: str

    def has_field(self, key_pattern: str) -> bool:
        return any(
            match["value"] == self.value and re.fullmatch(key_pattern, match["key"])
            for match in QUOTED_FIELD.finditer(self.line)
        )


def is_metadata(candidate: Candidate) -> bool:
    if candidate.kind not in ENTROPY_TYPES:
        return False
    if candidate.has_field(r"(?:\w+_)?sha(?:1|256|512)"):
        return bool(re.fullmatch(r"(?:[0-9a-fA-F]{40}|[0-9a-fA-F]{64}|[0-9a-fA-F]{128})", candidate.value))
    if candidate.filename.endswith(".json") and candidate.has_field("list_id"):
        return True
    if candidate.has_field("repo_id|local_dir"):
        return bool(re.fullmatch(r"[\w.-]+/[\w.-]+", candidate.value))
    return is_xmp_metadata(candidate)


def is_xmp_metadata(candidate: Candidate) -> bool:
    if not candidate.filename.endswith(".xmp"):
        return False
    if candidate.has_field("darktable:blendop_params"):
        return True
    # detect-secrets retries XML through eager transformers after filtering the
    # original value. Those can append a self-closing slash or quote escape to the candidate.
    # Verify against the original named attribute instead of trusting that parse.
    try:
        original = Path(candidate.filename).read_text()
    except (OSError, UnicodeError):
        return False
    return any(
        match["key"] == "darktable:blendop_params"
        and candidate.value in {match["value"] + "/", match["value"] + "\\"}
        for match in QUOTED_FIELD.finditer(original)
    )


def is_environment_name(candidate: Candidate) -> bool:
    return (
        candidate.kind == "Secret Keyword"
        and candidate.filename.endswith(".py")
        and bool(re.fullmatch(r"[A-Z][A-Z0-9_]+", candidate.value))
        and candidate.has_field(r"(?:[A-Z][A-Z0-9_]*_ENV|ENV_[A-Z0-9_]+)")
    )


@dataclass(frozen=True)
class EncodedImages:
    lines: frozenset[str]


@lru_cache(maxsize=8)
def encoded_images(filename: str, _mtime_ns: int) -> EncodedImages:
    """Cache MIME image bodies; mtime is part of the key so edits invalidate it."""
    message = BytesParser(policy=policy.default).parsebytes(Path(filename).read_bytes())
    lines: set[str] = set()
    for part in message.walk():
        if (
            part.get_content_maintype() != "image"
            or part.get("Content-Transfer-Encoding", "").lower() != "base64"
        ):
            continue
        # Multipart messages have main type "multipart" and were skipped above,
        # so an image part's undecoded payload is always text here.
        payload = cast(str, part.get_payload())
        lines.update(payload.splitlines())
    return EncodedImages(frozenset(lines))


def is_mime_image(candidate: Candidate) -> bool:
    if candidate.kind != "Artifactory Credentials" or Path(candidate.filename).suffix.lower() not in {
        ".mht",
        ".mhtml",
    }:
        return False
    if not re.fullmatch(r"[A-Za-z0-9+/]+={0,2}", candidate.line.strip()):
        return False
    try:
        images = encoded_images(candidate.filename, Path(candidate.filename).stat().st_mtime_ns)
    except OSError:
        return False
    return candidate.line.strip() in images.lines


def is_inline_image(candidate: Candidate) -> bool:
    # A provider-token-shaped substring inside encoded pixels is not a token.
    # Require an image signature, and retain the candidate if it also occurs
    # outside the data payload (including elsewhere on the same line).
    line = candidate.line
    if "data:image/" not in line and "image/" in line and ";base64," in line:
        # The eager INI transformer rewrites data: into data = "...".
        # Consult original text, retaining any occurrence outside image data.
        try:
            line = Path(candidate.filename).read_text()
        except (OSError, UnicodeError):
            return False
    for match in re.finditer(r"data:image/(?:png|jpeg|gif|webp);base64,([A-Za-z0-9+/=]+)", line):
        encoded = match[1]
        if candidate.value not in encoded:
            continue
        try:
            header = base64.b64decode(encoded[:32], validate=True)
        except binascii.Error:
            continue
        recognized = header.startswith((b"\x89PNG\r\n\x1a\n", b"\xff\xd8\xff", b"GIF87a", b"GIF89a"))
        recognized = recognized or (header.startswith(b"RIFF") and header[8:12] == b"WEBP")
        outside = line[: match.start(1)] + line[match.end(1) :]
        if recognized and candidate.value not in outside:
            return True
    return False


def is_vault_noncredential(secret: str, line: str, plugin: object, filename: str) -> bool:
    """detect-secrets filter boundary: operate on this candidate, not its line."""
    kind = getattr(plugin, "secret_type", None)
    if not isinstance(kind, str):
        return False
    candidate = Candidate(secret, line, kind, filename)
    if kind in {"Secret Keyword", "Basic Auth Credentials"} and PLACEHOLDER.fullmatch(secret):
        return True
    return (
        is_metadata(candidate)
        or is_environment_name(candidate)
        or is_mime_image(candidate)
        or is_inline_image(candidate)
    )


def is_android_ui_boolean(secret: str, line: str, plugin: object, context: object) -> bool:
    """Require Android UI context; an actual password equal to 'false' still alerts."""
    if getattr(plugin, "secret_type", None) != "Secret Keyword" or secret not in {"true", "false"}:
        return False
    previous = getattr(context, "previous_line", "")
    if not isinstance(previous, str):
        return False
    ui_context = bool(re.search(r"SystemUI|keyguard|<node\b[^>]*\bclass=", previous + line))
    return ui_context and bool(re.search(r'\bpassword="(?:true|false)"', line))
