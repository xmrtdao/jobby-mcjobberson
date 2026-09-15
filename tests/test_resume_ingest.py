import http.client
import json
import tempfile
import threading
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

from pypdf import PdfWriter
from pypdf._page import PageObject
from pypdf.generic import (
    ArrayObject,
    DecodedStreamObject,
    DictionaryObject,
    EncodedStreamObject,
    NameObject,
    NumberObject,
)

from resume_ingest import (
    MAX_DOCX_DOCUMENT_XML_BYTES,
    MAX_PDF_CONTENT_BYTES,
    MAX_RESUME_TEXT_BYTES,
    extract_resume_text,
    ingest_resume,
)


ROOT = Path(__file__).resolve().parents[1]


W_NS = "http://schemas.openxmlformats.org/wordprocessingml/2006/main"


def make_docx(path: Path, paragraphs: list[str]) -> None:
    document = ET.Element(f"{{{W_NS}}}document")
    body = ET.SubElement(document, f"{{{W_NS}}}body")
    for paragraph in paragraphs:
        p = ET.SubElement(body, f"{{{W_NS}}}p")
        for part in paragraph.split(" "):
            run = ET.SubElement(p, f"{{{W_NS}}}r")
            text = ET.SubElement(run, f"{{{W_NS}}}t")
            text.text = part + " "
    xml = ET.tostring(document, encoding="utf-8", xml_declaration=True)
    content_types = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/>
</Types>"""
    relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/>
</Relationships>"""
    document_relationships = """<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"/>"""
    with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("[Content_Types].xml", content_types)
        archive.writestr("_rels/.rels", relationships)
        archive.writestr("word/_rels/document.xml.rels", document_relationships)
        archive.writestr("word/document.xml", xml)


def make_pdf(path: Path, text: str) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
    stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
    stream_ref = writer._add_object(stream)
    page[NameObject("/Contents")] = stream_ref
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    resources = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
    })
    page[NameObject("/Resources")] = resources
    with path.open("wb") as output:
        writer.write(output)


def make_pdf_pages(path: Path, texts: list[str]) -> None:
    writer = PdfWriter()
    for text in texts:
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        escaped = text.replace("\\", "\\\\").replace("(", "\\(").replace(")", "\\)")
        stream.set_data(f"BT /F1 12 Tf 72 720 Td ({escaped}) Tj ET".encode("ascii"))
        page[NameObject("/Contents")] = writer._add_object(stream)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
        })
    with path.open("wb") as output:
        writer.write(output)


def make_compressed_pdf(path: Path, raw_content: bytes) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    stream.set_data(raw_content)
    compressed_stream = stream.flate_encode()
    page[NameObject("/Contents")] = writer._add_object(compressed_stream)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
    })
    with path.open("wb") as output:
        writer.write(output)


def make_compressed_pdf_pages(path: Path, raw_contents: list[bytes]) -> None:
    writer = PdfWriter()
    for raw_content in raw_contents:
        page = writer.add_blank_page(width=612, height=792)
        stream = DecodedStreamObject()
        stream.set_data(raw_content)
        compressed_stream = stream.flate_encode()
        page[NameObject("/Contents")] = writer._add_object(compressed_stream)
        font = DictionaryObject({
            NameObject("/Type"): NameObject("/Font"),
            NameObject("/Subtype"): NameObject("/Type1"),
            NameObject("/BaseFont"): NameObject("/Helvetica"),
        })
        font_ref = writer._add_object(font)
        page[NameObject("/Resources")] = DictionaryObject({
            NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
        })
    with path.open("wb") as output:
        writer.write(output)


def make_pdf_with_filter(path: Path, filter_name: str, data: bytes) -> None:
    writer = PdfWriter()
    page = writer.add_blank_page(width=612, height=792)
    stream = DecodedStreamObject()
    stream.set_data(data)
    stream[NameObject("/Filter")] = NameObject(filter_name)
    page[NameObject("/Contents")] = writer._add_object(stream)
    font = DictionaryObject({
        NameObject("/Type"): NameObject("/Font"),
        NameObject("/Subtype"): NameObject("/Type1"),
        NameObject("/BaseFont"): NameObject("/Helvetica"),
    })
    font_ref = writer._add_object(font)
    page[NameObject("/Resources")] = DictionaryObject({
        NameObject("/Font"): DictionaryObject({NameObject("/F1"): font_ref})
    })
    with path.open("wb") as output:
        writer.write(output)


def encode_run_length(data: bytes) -> bytes:
    encoded = bytearray()
    index = 0
    while index < len(data):
        if index + 1 < len(data) and data[index] == data[index + 1]:
            run_length = 1
            while (
                run_length < 128
                and index + run_length < len(data)
                and data[index + run_length] == data[index]
            ):
                run_length += 1
            encoded.append(257 - run_length)
            encoded.append(data[index])
            index += run_length
            continue

        literal_start = index
        index += 1
        while (
            index < len(data)
            and index - literal_start < 128
            and (index + 1 >= len(data) or data[index] != data[index + 1])
        ):
            index += 1
        literal_length = index - literal_start
        encoded.append(literal_length - 1)
        encoded.extend(data[literal_start:index])
    encoded.append(128)
    return bytes(encoded)


def make_multipart(
    filename: str,
    body: bytes,
    content_type: str = "text/plain",
    fields: dict[str, str] | None = None,
    field_name: str = "resume",
) -> tuple[bytes, str]:
    boundary = b"jobby-resume-test-boundary"
    disposition = (
        b'Content-Disposition: form-data; name="'
        + field_name.encode("ascii")
        + b'"; filename="'
        + filename.encode("utf-8")
        + b'"\r\n'
    )
    payload = (
        b"--"
        + boundary
        + b"\r\n"
        + disposition
        + b"Content-Type: "
        + content_type.encode("ascii")
        + b"\r\n\r\n"
        + body
        + b"\r\n"
    )
    for name, value in (fields or {}).items():
        payload += (
            b"--"
            + boundary
            + b"\r\nContent-Disposition: form-data; name=\""
            + name.encode("ascii")
            + b'"\r\n\r\n'
            + value.encode("utf-8")
            + b"\r\n"
        )
    payload += b"--" + boundary + b"--\r\n"
    return payload, "multipart/form-data; boundary=" + boundary.decode("ascii")


class ResumeIngestTest(unittest.TestCase):
    def test_extracts_raw_source_text_and_structured_portfolio_urls(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jane.txt"
            path.write_text(
                "Jane Doe\nSystems Architect\n"
                "https://jane.example.com/portfolio\njane@example.com\n",
                encoding="utf-8",
            )

            raw_text = extract_resume_text(path)
            result = ingest_resume(path)

        self.assertEqual(
            raw_text,
            "Jane Doe\nSystems Architect\nhttps://jane.example.com/portfolio\njane@example.com",
        )
        self.assertEqual(
            result["portfolio_urls"],
            ["https://jane.example.com/portfolio"],
        )
        self.assertEqual(result["portfolio_urls"], result["urls"])

    def test_ingests_plain_text_resume_and_extracts_explicit_links(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jane.txt"
            path.write_text(
                "Jane Doe\nSystems Architect\nSkills: Python, Kubernetes, AWS\n"
                "Portfolio: https://jane.example.com/portfolio\njane@example.com\n",
                encoding="utf-8",
            )

            result = ingest_resume(path)

        self.assertEqual(result["format"], "txt")
        self.assertIn("Systems Architect", result["text"])
        self.assertIn("Python", result["skills"])
        self.assertIn("Kubernetes", result["skills"])
        self.assertIn("AWS", result["skills"])
        self.assertIn("Architecture", result["job_fields"])
        self.assertIn("Cloud Engineering", result["job_fields"])
        self.assertNotIn("JavaScript", result["skills"])
        self.assertEqual(result["urls"], ["https://jane.example.com/portfolio"])
        self.assertEqual(result["emails"], ["jane@example.com"])
        self.assertEqual(result["urls_found"], 1)
        self.assertEqual(result["emails_found"], 1)

    def test_ingests_docx_resume_text_without_inventing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jane.docx"
            make_docx(
                path,
                [
                    "Jane Doe",
                    "Systems Architect",
                    "Python Kubernetes AWS",
                    "https://jane.example.com/portfolio",
                ],
            )

            result = ingest_resume(path)

        self.assertEqual(result["format"], "docx")
        self.assertIn("Jane Doe", result["text"])
        self.assertIn("Systems Architect", result["text"])
        self.assertIn("Python", result["text"])
        self.assertEqual(result["urls"], ["https://jane.example.com/portfolio"])

    def test_ingests_pdf_resume_text_without_inventing_content(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jane.pdf"
            make_pdf(path, "Jane Doe - Systems Architect - Python Kubernetes AWS")

            result = ingest_resume(path)

        self.assertEqual(result["format"], "pdf")
        self.assertIn("Jane Doe", result["text"])
        self.assertIn("Systems Architect", result["text"])
        self.assertIn("Python", result["text"])

    def test_rejects_pdf_with_oversized_compressed_content_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "compressed.pdf"
            make_compressed_pdf(path, b" " * (MAX_PDF_CONTENT_BYTES + 1))

            with self.assertRaisesRegex(ValueError, "PDF content stream exceeds"):
                ingest_resume(path)

    def test_rejects_pdf_with_high_expansion_run_length_stream(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "run-length.pdf"
            make_pdf_with_filter(
                path,
                "/RunLengthDecode",
                encode_run_length(b"x" * (MAX_PDF_CONTENT_BYTES + 1)),
            )

            with self.assertRaisesRegex(ValueError, "PDF content stream exceeds"):
                ingest_resume(path)

    def test_rejects_pdf_when_decoded_content_streams_exceed_cumulative_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "many-streams.pdf"
            stream = b"BT /F1 12 Tf 72 720 Td (x) Tj ET %" + b" " * (
                MAX_PDF_CONTENT_BYTES // 2
            )
            make_compressed_pdf_pages(path, [stream, stream, stream])

            with self.assertRaisesRegex(ValueError, "PDF decoded content exceeds"):
                ingest_resume(path)

    def test_rejects_pdf_when_extracted_text_exceeds_cumulative_budget(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "long-text.pdf"
            text = "x" * (MAX_RESUME_TEXT_BYTES // 3 + 1024)
            stream = (
                b"BT /F1 12 Tf 72 720 Td ("
                + text.encode("ascii")
                + b") Tj ET"
            )
            make_compressed_pdf_pages(path, [stream, stream, stream])

            with self.assertRaisesRegex(ValueError, "extracted PDF text exceeds"):
                ingest_resume(path)

    def test_rejects_unsupported_resume_formats(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jane.png"
            path.write_bytes(b"not a resume")

            with self.assertRaises(ValueError):
                ingest_resume(path)

    def test_http_endpoint_rejects_multipart_file_with_wrong_field_name(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.txt",
                b"Jane Doe\n",
                field_name="attachment",
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()
            response.read()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_conflicting_multipart_format_signals(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.png",
                b"Jane Doe\n",
                "text/plain",
                fields={"format": "txt"},
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()
            response.read()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_accepts_multipart_resume_upload(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.txt",
                b"Jane Doe\nSystems Architect\nSkills: Python, Kubernetes, AWS\njane@example.com\nhttps://jane.example.com\n",
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()
            result = json.loads(response.read())

            self.assertEqual(response.status, 200)
            self.assertEqual(result["format"], "txt")
            self.assertEqual(result["file"], "jane.txt")
            self.assertEqual(
                result["text"],
                "Jane Doe\nSystems Architect\nSkills: Python, Kubernetes, AWS\njane@example.com\nhttps://jane.example.com",
            )
            self.assertNotIn("jobby-resume-test-boundary", result["text"])
            self.assertEqual(result["skills"], ["Python", "Kubernetes", "AWS"])
            self.assertIn("Architecture", result["job_fields"])
            self.assertIn("Cloud Engineering", result["job_fields"])
            self.assertEqual(result["emails"], ["jane@example.com"])
            self.assertEqual(result["urls"], ["https://jane.example.com"])
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_server_serves_the_public_portal(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT / "docs")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/index.html")
            response = connection.getresponse()
            body = response.read().decode("utf-8")

            self.assertEqual(response.status, 200)
            self.assertIn("resume-drop-zone", body)
            self.assertIn("app.js", body)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_path_traversal_filenames(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=b"Jane Doe\n",
                headers={
                    "Content-Type": "text/plain",
                    "X-File-Name": "../outside.txt",
                },
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_declared_pdf_that_is_not_a_pdf(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.pdf",
                b"not a pdf",
                "application/pdf",
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_malformed_pdf_with_valid_header(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.pdf",
                b"%PDF-1.4\nnot a valid PDF body\n%%EOF\n",
                "application/pdf",
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()
            response.read()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_malformed_docx_upload(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.docx",
                b"not a docx",
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_docx_with_oversized_document_xml(self):
        from resume_server import create_server

        with tempfile.TemporaryDirectory() as directory:
            archive_path = Path(directory) / "compressed.docx"
            with zipfile.ZipFile(archive_path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("word/document.xml", b"x" * (MAX_DOCX_DOCUMENT_XML_BYTES + 1))
            multipart_body, content_type = make_multipart(
                "compressed.docx",
                archive_path.read_bytes(),
                "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            )

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        connection = None
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=multipart_body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()
            response.read()

            self.assertEqual(response.status, 400)
        finally:
            if connection is not None:
                connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_rejects_docx_that_extracts_beyond_text_limit(self):
        oversized_text = "x" * (MAX_RESUME_TEXT_BYTES + 1)
        document = ET.fromstring(
            f'<w:document xmlns:w="{W_NS}"><w:body><w:p><w:r><w:t>{oversized_text}</w:t></w:r></w:p></w:body></w:document>'
        )
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "oversized.docx"
            with zipfile.ZipFile(path, "w", compression=zipfile.ZIP_DEFLATED) as archive:
                archive.writestr("word/document.xml", ET.tostring(document))

            with self.assertRaisesRegex(ValueError, "extracted DOCX text exceeds"):
                ingest_resume(path)

    def test_http_endpoint_rejects_multipart_file_without_content_type(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            boundary = b"jobby-no-content-type"
            body = (
                b"--" + boundary
                + b'\r\nContent-Disposition: form-data; name="resume"; filename="jane.txt"\r\n\r\n'
                + b"Jane Doe\n"
                + b"\r\n--" + boundary + b"--\r\n"
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": "multipart/form-data; boundary=jobby-no-content-type"},
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_head_to_parser_endpoint_returns_method_not_allowed(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT / "docs")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("HEAD", "/api/resume/parse")
            response = connection.getresponse()

            self.assertEqual(response.status, 405)
            self.assertEqual(response.getheader("Allow"), "POST")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_extra_named_file_part(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            boundary = b"jobby-extra-file"
            body = (
                b"--" + boundary
                + b'\r\nContent-Disposition: form-data; name="resume"; filename="jane.txt"\r\nContent-Type: text/plain\r\n\r\n'
                + b"Jane Doe\n"
                + b"\r\n--" + boundary
                + b'\r\nContent-Disposition: form-data; name="attachment"; filename="secret.txt"\r\nContent-Type: text/plain\r\n\r\n'
                + b"not a resume\n"
                + b"\r\n--" + boundary + b"--\r\n"
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": "multipart/form-data; boundary=jobby-extra-file"},
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_windows_style_path_filename(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=b"Jane Doe\n",
                headers={
                    "Content-Type": "text/plain",
                    "X-File-Name": "C:\\Users\\jane\\resume.txt",
                },
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_filename_and_content_type_mismatch(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.txt",
                b"Jane Doe\\n",
                "application/pdf",
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_http_endpoint_rejects_disagreeing_format_signals(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            body, content_type = make_multipart(
                "jane.pdf",
                b"Jane Doe\n",
                "application/pdf",
                fields={"format": "txt"},
            )
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request(
                "POST",
                "/api/resume/parse",
                body=body,
                headers={"Content-Type": content_type},
            )
            response = connection.getresponse()

            self.assertEqual(response.status, 400)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_parser_rejects_pdf_magic_mismatch(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "jane.pdf"
            path.write_text("Jane Doe\n", encoding="utf-8")

            with self.assertRaises(ValueError):
                ingest_resume(path)

    def test_static_server_rejects_unlisted_asset(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT / "docs")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/README.md")
            response = connection.getresponse()
            response.read()

            self.assertEqual(response.status, 404)
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_static_server_rejects_unlisted_nested_asset(self):
        from resume_server import create_server

        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / "index.html").write_text("<!doctype html>", encoding="utf-8")
            (root / "secret.txt").write_text("secret", encoding="utf-8")
            server = create_server("127.0.0.1", 0, root)
            thread = threading.Thread(target=server.serve_forever, daemon=True)
            thread.start()
            connection = None
            try:
                connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
                connection.request("GET", "/secret.txt")
                response = connection.getresponse()
                response.read()

                self.assertEqual(response.status, 404)
            finally:
                if connection is not None:
                    connection.close()
                server.shutdown()
                server.server_close()
                thread.join(timeout=5)

    def test_static_responses_include_security_headers(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT / "docs")
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/index.html")
            response = connection.getresponse()
            response.read()

            self.assertEqual(response.status, 200)
            policy = response.getheader("Content-Security-Policy")
            self.assertIn("default-src 'self'", policy)
            self.assertNotIn("unsafe-inline", policy)
            self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
            self.assertEqual(response.getheader("Referrer-Policy"), "no-referrer")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)

    def test_parser_responses_include_security_headers(self):
        from resume_server import create_server

        server = create_server("127.0.0.1", 0, ROOT)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        try:
            connection = http.client.HTTPConnection("127.0.0.1", server.server_port, timeout=5)
            connection.request("GET", "/api/resume/parse")
            response = connection.getresponse()
            response.read()

            self.assertEqual(response.status, 405)
            policy = response.getheader("Content-Security-Policy")
            self.assertIn("default-src 'self'", policy)
            self.assertNotIn("unsafe-inline", policy)
            self.assertEqual(response.getheader("X-Frame-Options"), "DENY")
        finally:
            connection.close()
            server.shutdown()
            server.server_close()
            thread.join(timeout=5)


if __name__ == "__main__":
    unittest.main()
