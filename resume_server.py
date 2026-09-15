#!/usr/bin/env python3
"""Serve the static hero and parse resumes through one same-origin endpoint."""

from __future__ import annotations

import json
import tempfile
from email import policy
from email.parser import BytesParser
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import unquote, urlsplit

from resume_ingest import (
    MAX_RESUME_BYTES,
    _SUPPORTED_FORMATS,
    ingest_resume,
)


_FORMATS_BY_CONTENT_TYPE = {
    "application/pdf": "pdf",
    "application/vnd.openxmlformats-officedocument.wordprocessingml.document": "docx",
    "text/plain": "txt",
}
_STATIC_CONTENT_TYPES = {
    ".css": "text/css; charset=utf-8",
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".pdf": "application/pdf",
    ".txt": "text/plain; charset=utf-8",
}
_STATIC_ASSETS = {"index.html", "styles.css", "app.js"}
_SECURITY_HEADERS = {
    "Content-Security-Policy": (
        "default-src 'self'; script-src 'self'; "
        "style-src 'self'; img-src 'self' data:; "
        "connect-src 'self'; frame-ancestors 'none'; base-uri 'self'; "
        "form-action 'self'; object-src 'none'"
    ),
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
}
_MAX_MULTIPART_OVERHEAD = 1024 * 1024


def _safe_filename(value: str | None) -> str:
    filename = unquote(value or "").strip()
    if (
        not filename
        or "\x00" in filename
        or "/" in filename
        or "\\" in filename
        or filename in {".", ".."}
        or Path(filename).name != filename
    ):
        raise ValueError("invalid resume filename")
    return filename


def _format_for_request(
    filename: str,
    content_type: str,
    hint: str | None,
) -> str:
    """Resolve format only when every supplied signal agrees."""
    hint_value = (hint or "").strip().lower().lstrip(".")
    media_type = content_type.split(";", 1)[0].strip().lower()
    media_value = _FORMATS_BY_CONTENT_TYPE.get(media_type)
    suffix_value = Path(filename).suffix.lower().lstrip(".")
    if not media_value:
        raise ValueError("unsupported resume format")
    if hint_value and hint_value not in _SUPPORTED_FORMATS:
        raise ValueError("unsupported resume format")
    if suffix_value and suffix_value not in _SUPPORTED_FORMATS:
        raise ValueError("unsupported resume format")
    signals = [media_value]
    if suffix_value:
        signals.append(suffix_value)
    if hint_value:
        signals.append(hint_value)
    if len(set(signals)) != 1:
        raise ValueError("conflicting resume format signals")
    return next(iter(signals))


def _multipart_upload(
    body: bytes,
    content_type: str,
) -> tuple[str, bytes, str, dict[str, str]]:
    """Extract exactly one resume part without using the removed cgi module."""
    if not content_type.lower().startswith("multipart/form-data"):
        raise ValueError("multipart resume upload required")
    if "boundary=" not in content_type.lower():
        raise ValueError("multipart boundary missing")

    message = BytesParser(policy=policy.default).parsebytes(
        b"Content-Type: "
        + content_type.encode("latin-1", errors="replace")
        + b"\r\nMIME-Version: 1.0\r\n\r\n"
        + body
    )
    if not message.is_multipart():
        raise ValueError("invalid multipart resume upload")

    file_parts: list[tuple[str, bytes, str]] = []
    fields: dict[str, str] = {}
    for part in message.iter_parts():
        filename = part.get_filename()
        if filename is not None:
            name = part.get_param("name", header="content-disposition")
            if name != "resume":
                raise ValueError("resume field name missing")
            if part.get("Content-Type") is None:
                raise ValueError("resume file content type missing")
            file_parts.append(
                (
                    filename,
                    part.get_payload(decode=True) or b"",
                    part.get_content_type(),
                )
            )
            continue

        name = part.get_param("name", header="content-disposition")
        if name:
            payload = part.get_payload(decode=True)
            if payload is None:
                raw_payload = part.get_payload()
                payload = (
                    raw_payload.encode("utf-8")
                    if isinstance(raw_payload, str)
                    else b""
                )
            fields[name] = payload.decode("utf-8", errors="replace")

    if len(file_parts) != 1:
        raise ValueError("exactly one resume file is required")
    filename, payload, part_content_type = file_parts[0]
    return _safe_filename(filename), payload, part_content_type, fields


def _extract_resume_upload(
    body: bytes,
    content_type: str,
    header_filename: str | None,
    hint: str | None,
) -> tuple[str, bytes, str, str | None]:
    media_type = content_type.split(";", 1)[0].strip().lower()
    if media_type.startswith("multipart/form-data"):
        filename, payload, part_content_type, fields = _multipart_upload(
            body, content_type
        )
        return (
            filename,
            payload,
            part_content_type,
            fields.get("format") or fields.get("hint") or hint,
        )

    filename = _safe_filename(header_filename)
    return filename, body, content_type, hint


def create_server(
    host: str = "127.0.0.1",
    port: int = 0,
    root: Path | None = None,
):
    """Create a local static portal and parser server."""
    static_root = (root or Path(__file__).parent / "docs").resolve()

    class ResumeHTTPServer(ThreadingHTTPServer):
        daemon_threads = True

    class ResumeRequestHandler(BaseHTTPRequestHandler):
        server_version = "JobbyResumeParser/1"

        def _send_security_headers(self) -> None:
            for name, value in _SECURITY_HEADERS.items():
                self.send_header(name, value)

        def do_GET(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            path = urlsplit(self.path).path
            if path == "/api/resume/parse":
                self._write_json(405, {"error": "method not allowed"}, {"Allow": "POST"})
                return
            self._serve_static(path, send_body=True)

        def do_HEAD(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlsplit(self.path).path == "/api/resume/parse":
                self._write_json(405, {"error": "method not allowed"}, {"Allow": "POST"}, send_body=False)
                return
            self._serve_static(urlsplit(self.path).path, send_body=False)

        def do_POST(self) -> None:  # noqa: N802 - BaseHTTPRequestHandler API
            if urlsplit(self.path).path != "/api/resume/parse":
                self._write_json(404, {"error": "not found"})
                return

            try:
                raw_length = self.headers.get("Content-Length", "")
                content_length = int(raw_length)
                if (
                    content_length <= 0
                    or content_length > MAX_RESUME_BYTES + _MAX_MULTIPART_OVERHEAD
                ):
                    raise ValueError("invalid resume size")
                body = self.rfile.read(content_length)
                if len(body) != content_length:
                    raise ValueError("incomplete resume upload")

                content_type = self.headers.get("Content-Type", "")
                filename, payload, part_content_type, hint = _extract_resume_upload(
                    body,
                    content_type,
                    self.headers.get("X-File-Name"),
                    self.headers.get("X-Format-Hint"),
                )
                if len(payload) > MAX_RESUME_BYTES:
                    raise ValueError("resume exceeds the 10 MB limit")
                resume_format = _format_for_request(
                    filename, part_content_type, hint
                )

                with tempfile.NamedTemporaryFile(
                    suffix=f".{resume_format}", delete=False
                ) as upload:
                    upload.write(payload)
                    upload_path = Path(upload.name)
                try:
                    result = ingest_resume(upload_path, hint=resume_format)
                finally:
                    upload_path.unlink(missing_ok=True)
                result["file"] = filename
                self._write_json(200, result)
            except (FileNotFoundError, ValueError, OSError, TypeError) as error:
                self._write_json(400, {"error": str(error)})
            except Exception:
                self._write_json(500, {"error": "resume parsing failed"})

        def _static_path(self, request_path: str) -> Path | None:
            relative_path = unquote(request_path).lstrip("/") or "index.html"
            if "/" in relative_path:
                return None
            candidate = (static_root / relative_path).resolve()
            try:
                candidate.relative_to(static_root)
            except ValueError:
                return None
            if candidate.parent != static_root or candidate.name not in _STATIC_ASSETS:
                return None
            if not candidate.is_file():
                return None
            return candidate

        def _serve_static(self, request_path: str, send_body: bool) -> None:
            path = self._static_path(request_path)
            if path is None:
                self._write_json(404, {"error": "not found"})
                return
            try:
                payload = path.read_bytes()
            except OSError:
                self._write_json(404, {"error": "not found"})
                return
            content_type = _STATIC_CONTENT_TYPES.get(
                path.suffix.lower(), "application/octet-stream"
            )
            self.send_response(200)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(payload)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            self.end_headers()
            if send_body:
                self.wfile.write(payload)

        def _write_json(
            self,
            status: int,
            payload: dict[str, Any],
            extra_headers: dict[str, str] | None = None,
            send_body: bool = True,
        ) -> None:
            body = json.dumps(payload).encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(body)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self._send_security_headers()
            for name, value in (extra_headers or {}).items():
                self.send_header(name, value)
            self.end_headers()
            if send_body:
                self.wfile.write(body)

        def log_message(self, format: str, *args: Any) -> None:
            return

    return ResumeHTTPServer((host, port), ResumeRequestHandler)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--root", type=Path, default=Path(__file__).parent / "docs")
    args = parser.parse_args()
    server = create_server(args.host, args.port, args.root)
    print(f"Jobby portal listening on http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()
