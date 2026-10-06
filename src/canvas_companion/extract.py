"""Isolated document extraction process; bounded input, CPU and output."""

import json
import resource
import sys
import zipfile
from html.parser import HTMLParser
from io import BytesIO

from defusedxml import ElementTree
from pypdf import PdfReader


class TextHTML(HTMLParser):
    def __init__(self):
        super().__init__()
        self.parts, self.hidden = [], 0

    def handle_starttag(self, tag, attrs):
        if tag in {"script", "style"}:
            self.hidden += 1

    def handle_endtag(self, tag):
        if tag in {"script", "style"}:
            self.hidden = max(0, self.hidden - 1)

    def handle_data(self, data):
        if not self.hidden:
            self.parts.append(data)


def extract(raw, kind, maximum):
    if kind == "pdf":
        reader = PdfReader(BytesIO(raw))
        parts, size = [], 0
        for page in reader.pages:
            text = page.extract_text() or ""
            parts.append(text[: maximum + 1])
            size += len(text)
            if size > maximum:
                break
        text = "\n".join(parts)
    elif kind in {"docx", "pptx", "xlsx"}:
        with zipfile.ZipFile(BytesIO(raw)) as archive:
            entries = archive.infolist()
            if len(entries) > 2000 or sum(e.file_size for e in entries) > 30 * 1024 * 1024:
                raise ValueError("Archive exceeds limits")
            parts = []
            for entry in entries:
                name = entry.filename
                if (
                    name == "word/document.xml"
                    or name.startswith("ppt/slides/slide")
                    or name == "xl/sharedStrings.xml"
                    or name.startswith("xl/worksheets/sheet")
                ) and name.endswith(".xml"):
                    root = ElementTree.fromstring(archive.read(entry))
                    parts.extend(
                        t.text or "" for t in root.iter() if t.tag.rsplit("}", 1)[-1] in {"t", "v"}
                    )
            text = "\n".join(parts)
        if kind == "xlsx":
            text = (
                "Spreadsheet text extract (not a rendered table; shared-string indexes may appear):\n"
                + text
            )
    elif kind in {"html", "htm"}:
        parser = TextHTML()
        parser.feed(raw.decode("utf-8", "replace"))
        text = "\n".join(parser.parts)
    else:
        text = raw.decode("utf-8", "replace")
    return {"text": text[:maximum], "truncated": len(text) > maximum, "extractable": True}


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (15, 15))
    if sys.platform == "linux":
        resource.setrlimit(resource.RLIMIT_AS, (512 * 1024 * 1024, 512 * 1024 * 1024))
    raw = sys.stdin.buffer.read(10 * 1024 * 1024 + 1)
    if len(raw) > 10 * 1024 * 1024:
        raise SystemExit(1)
    print(json.dumps(extract(raw, sys.argv[1], min(120000, int(sys.argv[2])))))
