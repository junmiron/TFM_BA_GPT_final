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
)
from langchain.document_loaders import WebBaseLoader
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


def read_txt_file(file_path: str) -> str:
    """
    Reads the content of a .txt file and returns it as a string.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"


def read_pdf_file(file_path: str) -> str:
    """
    Reads the content of a .pdf file and returns it as a string.
    """
    try:
        loader = PyMuPDFLoader(file_path)
        documents = loader.load()
        return documents[0].page_content if documents else ""
    except Exception as e:
        return f"Error reading file: {e}"


def write_mermaid_to_file(mermaid_code: str, filename: str) -> None:
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
