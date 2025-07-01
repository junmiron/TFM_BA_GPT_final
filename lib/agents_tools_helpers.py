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


aasync def load_and_index_web_page(
    urls,
    vector_memory,
    chunk_size=500,
    chunk_overlap=50,
    output_dir="./cleaned_pages"
):
    if isinstance(urls, str):
        urls = [urls]

    os.makedirs(output_dir, exist_ok=True)

    text_splitter = RecursiveCharacterTextSplitter(
        chunk_size=chunk_size, chunk_overlap=chunk_overlap
    )

    cleaner = Cleaner(
        scripts=True,
        javascript=True,
        comments=True,
        style=True,
        inline_style=True,
        links=True,
        meta=True,
        page_structure=True,
        processing_instructions=True,
        embedded=True,
        frames=True,
        forms=True,
        annoying_tags=True,
        remove_unknown_tags=True,
        safe_attrs_only=True,
        add_nofollow=True,
        remove_tags=None,
        allow_tags=None,
        host_whitelist=[],
        safe_attrs=set(),
    )

    cleaner.kill_tags = [
        'noscript', 'iframe', 'header', 'footer', 'nav', 'aside',
        'script', 'style', 'form', 'input', 'button', 'select',
        'label', 'textarea', 'object', 'embed', 'applet', 'video',
        'audio', 'svg', 'canvas', 'figure', 'figcaption', 'template',
        'link'
    ]

    def extract_main_content(tree):
        candidates = []

        # Try semantic tags
        for tag in ['main', 'article', 'section']:
            elems = tree.xpath(f'//{tag}')
            candidates += elems

        # Heuristic search via class/id
        keywords = ['content', 'main', 'article', 'body', 'post', 'container']
        xpath_expr = "|".join([
            f"//*[contains(@class, '{k}') or contains(@id, '{k}')]" for k in keywords
        ])
        candidates += tree.xpath(xpath_expr)

        # Filter and rank candidates
        candidates = [el for el in candidates if len(el.text_content().split()) > 100]
        candidates = sorted(candidates, key=lambda el: len(el.text_content()), reverse=True)

        return candidates[0].text_content().strip() if candidates else tree.text_content().strip()

    async def process_url(url):
        try:
            loader = WebBaseLoader(url)
            docs = loader.load()

            for doc in docs:
                raw_html = doc.page_content

                # Extract readable HTML
                readable_doc = Document(raw_html)
                readable_html = readable_doc.summary()

                # Clean the HTML
                cleaned_html = cleaner.clean_html(readable_html)
                parsed = lxml.html.fromstring(cleaned_html)
                clean_text = parsed.text_content().strip()

                # Fallback to heuristics if too short
                if len(clean_text.split()) < 100:
                    clean_text = extract_main_content(parsed)

                # Save to file
                filename = url.replace("https://", "").replace("http://", "").replace("/", "_")
                filepath = os.path.join(output_dir, f"{filename}.txt")
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(clean_text)

                print(f"✅ Saved cleaned content to {filepath}")

                # Split and index
                chunks = text_splitter.split_text(clean_text)
                for i, chunk in enumerate(chunks):
                    await vector_memory.add(
                        MemoryContent(
                            content=chunk,
                            mime_type=MemoryMimeType.TEXT,
                            metadata={"source": url, "chunk_index": i}
                        )
                    )

                print(f"📚 Indexed {len(chunks)} chunks from {url}")

        except Exception as e:
            print(f"❌ Error processing {url}: {e}")

    tasks = [process_url(url) for url in urls]
    await asyncio.gather(*tasks)

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
