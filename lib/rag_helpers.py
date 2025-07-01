"""
This module provides helper functions for creating and managing ChromaDB-based
vector memory for retrieval-augmented generation (RAG) workflows.

The primary function, `create_chromadb_memory`, initializes a ChromaDB
collection with a local SentenceTransformer embedding function and
returns a vector memory object for use in RAG-enabled applications.
"""
import asyncio
import json
import os
from typing import Union

import lxml.html
from autogen_core.memory import MemoryContent, MemoryMimeType
from autogen_ext.memory.chromadb import (ChromaDBVectorMemory,
                                         PersistentChromaDBVectorMemoryConfig)
from chromadb.utils import embedding_functions
from langchain.text_splitter import RecursiveCharacterTextSplitter
from langchain_community.document_loaders import (
    PyMuPDFLoader, TextLoader, UnstructuredWordDocumentLoader, WebBaseLoader)
from lxml_html_clean import Cleaner
from readability import Document


async def create_chromadb_memory(
    chroma_dir: str, collection_name: str
) -> ChromaDBVectorMemory:
    """
    Create a ChromaDB collection with a local SentenceTransformer embedding
    function.

    Args:
        chroma_dir (str): Directory for ChromaDB persistence.
        collection_name (str): Name of the collection to create or load.

    Returns:
        ChromaDBVectorMemory: ChromaDB vector memory object with the specified collection.
    """

    # --- EMBEDDING FUNCTION (Local SentenceTransformer) --- #
    embedding_function = (
        embedding_functions.SentenceTransformerEmbeddingFunction(
            model_name="paraphrase-multilingual-mpnet-base-v2"
        )
    )

    # --- RAG-ENABLED AUTO-GEN SETUP WITH CHROMADB --- #
    # Using a specific Sentence Transformer model
    vector_memory = ChromaDBVectorMemory(
        config=PersistentChromaDBVectorMemoryConfig(
            collection_name=collection_name,
            persistence_path=chroma_dir,
            k=3,
            score_threshold=0.4,
            embedding_function=embedding_function,
        )
    )

    return vector_memory


async def load_and_index_documents(
    docs_dir: str,
    doc_vector_memory: ChromaDBVectorMemory,
    chunk_size: int = 500,
    chunk_overlap: int = 50
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
                await doc_vector_memory.add(
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
    urls: Union[str, list[str]],
    vector_memory: ChromaDBVectorMemory,
    chunk_size: int = 500,
    chunk_overlap: int = 50,
    output_dir: str = "./cleaned_pages"
):
    """
    Loads web pages from the given URLs, extracts and cleans their main
    content, splits the content into chunks, and indexes them into the
    provided vector memory.

    Args:
        urls (Union[str, list[str]]): A single URL or a list of URLs to
            process.
        vector_memory (ChromaDBVectorMemory): The vector memory object to
            index the content into.
        chunk_size (int, optional): Number of characters in each chunk.
            Defaults to 500.
        chunk_overlap (int, optional): Number of overlapping characters
            between chunks. Defaults to 50.
        output_dir (str, optional): Directory to save the cleaned text files.
            Defaults to "./cleaned_pages".

    Returns:
        tuple: (chunk_size, chunk_overlap)
    """
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
        remove_tags=[
            'noscript', 'iframe', 'header', 'footer', 'nav', 'aside',
            'script', 'style', 'form', 'input', 'button', 'select',
            'label', 'textarea', 'object', 'embed', 'applet', 'video',
            'audio', 'svg', 'canvas', 'figure', 'figcaption', 'template',
            'link'
        ],
        allow_tags=[],
        host_whitelist=[],
        safe_attrs=set(),
    )

    def extract_main_content(tree: lxml.html.HtmlElement) -> str:
        candidates: list[lxml.html.HtmlElement] = []

        # Try semantic tags
        for tag in ['main', 'article', 'section']:
            elems: list[lxml.html.HtmlElement] = tree.xpath(f'//{tag}')
            candidates += elems

        # Heuristic search via class/id
        keywords = ['content', 'main', 'article', 'body', 'post', 'container']
        xpath_expr = "|".join([
            f"//*[contains(@class, '{k}') or contains(@id, '{k}')]"
            for k in keywords
        ])
        candidates += tree.xpath(xpath_expr)

        # Filter and rank candidates
        candidates = [
            el
            for el in candidates
            if len(el.text_content().split()) > 100
        ]
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

def load_index_state(state_file_path):
    if not os.path.exists(state_file_path):
        return {"indexed_files": [], "indexed_urls": []}
    with open(state_file_path, "r") as f:
        return json.load(f)

def save_index_state(state, state_file_path):
    with open(state_file_path, "w") as f:
        json.dump(state, f, indent=2)