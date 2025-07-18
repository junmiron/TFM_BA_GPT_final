"""
This module provides utilities for loading and indexing documents
into vector memory. It supports PDF, TXT, and DOCX formats and
uses a text splitter to divide documents into smaller chunks
for efficient indexing.
"""
import os
import asyncio
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyMuPDFLoader,
    TextLoader,
    UnstructuredWordDocumentLoader,
    WebBaseLoader,
)
import fitz  # PyMuPDF
from autogen_core.memory import MemoryContent, MemoryMimeType

# --- INDEXING UTILITIES --- #

# Funtion to load and index documents
# This function loads documents from a specified directory,
# splits them into chunks, and indexes them in the provided vector memory.
# It supports PDF, TXT, and DOCX formats.
# The function uses a text splitter to divide the documents into smaller chunks
# based on the specified chunk size and overlap.
# It also handles exceptions for unsupported file formats and
# errors during processing.


def read_txt_file_tool(file_path: str) -> str:
    """
    Reads the content of a .txt file and returns it as a string.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


def read_pdf_file_tool(file_path: str) -> str:
    """
    Reads the content of a .pdf file and returns it as a string.
    """
    try:
        loader = PyMuPDFLoader(file_path)
        documents = loader.load()
        return documents[0].page_content if documents else ""
    except Exception as e:
        return f"Error reading file: {e}"


def write_pdf_file_tool(text: str, file_path: str):
    """
    Writes the given text into a PDF file at the specified path.
    """
    try:
        doc = fitz.open()  # New empty PDF
        page = doc.new_page()  # Add a new page
        # Simple insertion: top-left corner, can be customized
        page.insert_text((72, 72), text, fontsize=12)
        doc.save(file_path)
        doc.close()
        return f"PDF successfully written to {file_path}"
    except Exception as e:
        return f"Error writing PDF: {e}"


def write_mermaid_to_file_tool(mermaid_code: str, filename: str) -> None:
    """
    Write Mermaid diagram code to a .mmd file.

    Args:
        mermaid_code (str): The Mermaid syntax/code to write.
        filename (str): The name of the file to write to. Should end with '.mmd'.
    """
    if not filename.endswith('.mmd'):
        raise ValueError("Filename must end with '.mmd'")

    with open(filename, 'w', encoding='utf-8') as file:
        file.write("```mermaid\n")
        file.write(mermaid_code)
        file.write("\n```")

    print(f"Mermaid diagram written to {filename}")
