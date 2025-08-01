"""
This module provides agent tools.
"""
import os
import asyncio
import json
import fitz  # PyMuPDF
from datetime import datetime
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyMuPDFLoader,
    TextLoader,
    UnstructuredWordDocumentLoader,
    WebBaseLoader,
)
from autogen_core.memory import MemoryContent, MemoryMimeType

DEFAULT_JSONL_PATH = "../conversation/interview.jsonl"
DEFAULT_MD_PATH = "../conversation/final_summary.md"
DEFAULT_PDF_PATH = "../conversation/functional_specification.pdf"


import os
import fitz  # PyMuPDF

DEFAULT_PDF_PATH = "../conversation/functional_specification.pdf"

def read_pdf_file_tool(file_path: str = DEFAULT_PDF_PATH) -> str:
    """
    Reads the entire content of a PDF file and returns it as a string.

    Args:
        file_path (str): Optional custom PDF file path (defaults to DEFAULT_PDF_PATH).

    Returns:
        str: The full text content of the PDF, or an error message.
    """
    try:
        if not os.path.exists(file_path):
            return f"Error: PDF file not found at {file_path}"

        # Open the PDF
        doc = fitz.open(file_path)
        text = ""

        # Read all pages
        for page in doc:
            page_text = page.get_text("text")
            if page_text.strip():
                text += page_text + "\n"

        doc.close()

        if text.strip():
            return text.strip()
        else:
            return "PDF is empty — no readable text found."
    except Exception as e:
        return f"Error reading PDF: {e}"



def write_pdf_file_tool(text: str, file_path: str = DEFAULT_PDF_PATH) -> str:
    """
    Writes the given text into a PDF file.

    Args:
        text (str): The full text content to write into the PDF.
        file_path (str): Optional custom path for saving. Defaults to DEFAULT_PDF_PATH.

    Returns:
        str: Confirmation or error message.
    """
    try:
        # Ensure the folder exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Create and write PDF
        doc = fitz.open()  # New empty PDF
        page = doc.new_page()  # Add one page
        page.insert_text((72, 72), text, fontsize=12)  # 72,72 = 1 inch margins

        # Save and close
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


def save_conversation_to_jsonl(speaker: str, message: str, file_path: str = DEFAULT_JSONL_PATH):
    """
    Saves a single conversation turn (speaker + message) to a jsonl file.

    Args:
        speaker (str): Who is speaking (e.g., "interviewer" or "user").
        message (str): The content of the message.
    """
    try:
        with open(file_path, 'a', encoding='utf-8') as file:
            json_record = {
                "timestamp": datetime.utcnow().isoformat(),
                "speaker": speaker,
                "message": message
            }
            file.write(json.dumps(json_record) + "\n")
        return f"Saved message from {speaker} to {file_path}"
    except Exception as e:
        return f"Error saving message: {e}"


def save_summary_to_markdown(content: str, file_path: str = DEFAULT_MD_PATH):
    """
    Saves the final confirmed summary to a Markdown file.

    Args:
        content (str): The final summary text, formatted in Markdown.
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write(content)
        return f"Final summary successfully saved to {file_path}"
    except Exception as e:
        return f"Error saving final summary: {e}"
