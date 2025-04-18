"""
This module provides utilities for loading and indexing documents
into vector memory. It supports PDF, TXT, and DOCX formats and
uses a text splitter to divide documents into smaller chunks
for efficient indexing.
"""
import os
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


async def load_and_index_documents(
    docs_dir,
    vector_memory,
    chunk_size=500,
    chunk_overlap=50
):
    """
    Loads PDF, TXT, and DOCX documents from the specified directory,
    splits them into chunks, and indexes them in the provided
    AutoGen vector memory.

    Args:
        docs_dir (str): Path to the directory containing the documents.
        vector_memory (ChromaDBVectorMemory): The vector memory object to
        index the documents into.
        chunk_size (int): Number of characters in each chunk.
        chunk_overlap (int): Number of overlapping characters between chunks.
    """
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap)

    for file_name in os.listdir(docs_dir):
        file_path = os.path.join(docs_dir, file_name)
        ext = os.path.splitext(file_name)[-1].lower()

        try:
            if ext == ".pdf":
                loader = PyMuPDFLoader(file_path)
            elif ext == ".txt":
                loader = TextLoader(file_path)
            elif ext in [".doc", ".docx"]:
                loader = UnstructuredWordDocumentLoader(file_path)
            else:
                print(f"Unsupported file format: {file_name}")
                continue

            docs = loader.load()
            split_docs = text_splitter.split_documents(docs)

            for i, chunk in enumerate(split_docs):
                await vector_memory.add(  # Add `await` here
                    MemoryContent(
                        content=chunk.page_content,
                        mime_type=MemoryMimeType.TEXT,
                        metadata={"source": file_name, "chunk_index": i}
                    )
                )

            print(f"Indexed {len(split_docs)} chunks from {file_name}.")

        except (FileNotFoundError, ValueError, RuntimeError) as e:
            print(f"Error processing {file_name}: {e}")
    return chunk_size, chunk_overlap


async def load_and_index_web_page(
    url,
    vector_memory,
    chunk_size=500,
    chunk_overlap=50
):
    """
    Loads a web page from the specified URL, splits its content into chunks,
    and indexes the chunks in the provided AutoGen vector memory.

    Args:
        url (str): The URL of the web page to load.
        vector_memory: The vector memory object to index the web page into.
        chunk_size (int): Number of characters in each chunk.
        chunk_overlap (int): Number of overlapping characters between chunks.
    """
    # Instantiate the text splitter (same as for documents)
    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )

    try:
        # Use a web page loader from LangChain. If you prefer an alternate loader
        # (e.g., UnstructuredURLLoader) you can change it here.
        loader = WebBaseLoader(url)
        docs = loader.load()
        split_docs = text_splitter.split_documents(docs)

        for i, chunk in enumerate(split_docs):
            await vector_memory.add(
                MemoryContent(
                    content=chunk.page_content,
                    mime_type=MemoryMimeType.TEXT,
                    metadata={"source": url, "chunk_index": i}
                )
            )

        print(f"Indexed {len(split_docs)} chunks from {url}.")

    except Exception as e:
        print(f"Error processing {url}: {e}")

    return chunk_size, chunk_overlap

def read_txt_file(file_path: str) -> str:
    """
    Reads the content of a .txt file and returns it as a string.
    """
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            return f.read()
    except Exception as e:
        return f"Error reading file: {e}"