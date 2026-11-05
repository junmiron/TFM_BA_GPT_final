"""The RAG pipeline must stay free of langchain.

langchain-community is sunset and prints a DeprecationWarning on import, and
langchain 1.x removed `langchain.text_splitter` outright, so the split/load code
now lives in rag_helpers itself. These tests keep that true and check that the
replacement splitter behaves like the one it replaced.
"""
from pathlib import Path
import sys

import pytest

PROJECT_ROOT = Path(__file__).resolve().parent.parent
RAG = PROJECT_ROOT / "lib" / "rag_helpers.py"
sys.path.insert(0, str(PROJECT_ROOT / "lib"))


def test_rag_helpers_does_not_import_langchain():
    text = RAG.read_text(encoding="utf-8")
    for line in text.splitlines():
        if line.strip().startswith(("import langchain", "from langchain")):
            raise AssertionError(f"rag_helpers imports langchain: {line}")


def test_split_text_respects_chunk_size():
    from rag_helpers import split_text

    text = "\n\n".join("paragraph " * 200 for _ in range(20))
    chunks = split_text(text, chunk_size=500, chunk_overlap=50)
    assert chunks, "splitter produced no chunks"
    assert all(len(c) <= 500 for c in chunks), max(len(c) for c in chunks)
    # Nothing is dropped: every chunk is a substring of the original.
    assert all(c in text for c in chunks)
    # Overlapping chunks mean consecutive chunks share a tail/head.
    assert any(chunks[i][-40:] in chunks[i + 1] for i in range(len(chunks) - 1))


def test_split_text_keeps_short_documents_whole():
    from rag_helpers import split_text

    assert split_text("just a short note", 500, 50) == ["just a short note"]


def test_pdf_reader_returns_page_text(tmp_path):
    import pymupdf
    from rag_helpers import _read_pdf

    pdf = tmp_path / "spec.pdf"
    doc = pymupdf.open()
    page = doc.new_page()
    page.insert_text((72, 72), "Functional requirement 1: the system must export PDFs.")
    doc.save(str(pdf))
    doc.close()

    pages = _read_pdf(str(pdf))
    assert len(pages) == 1
    assert "export PDFs" in pages[0]


def test_docx_reader_extracts_paragraphs(tmp_path):
    from rag_helpers import _read_docx
    import zipfile

    docx = tmp_path / "doc.docx"
    body = (
        '<?xml version="1.0" encoding="UTF-8"?>'
        '<w:document xmlns:w="http://www.w3.org/2001/wordprocessingml/2006/main">'
        '<w:body><w:p><w:r><w:t>First requirement</w:t></w:r></w:p>'
        '<w:p><w:r><w:t>Second requirement</w:t></w:r></w:p></w:body></w:document>'
    )
    with zipfile.ZipFile(docx, "w") as zf:
        zf.writestr("word/document.xml", body)

    assert _read_docx(str(docx)) == ["First requirement", "Second requirement"]
