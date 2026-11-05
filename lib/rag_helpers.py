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
import re
import zipfile
import xml.etree.ElementTree as ET
import yaml  # Requires pyyaml
import httpx
import lxml.html
from lxml_html_clean import Cleaner
from autogen_core.memory import (
    MemoryContent,
    MemoryMimeType,
    MemoryQueryResult,
    UpdateContextResult,
)
from autogen_core.model_context import ChatCompletionContext
from autogen_core.models import UserMessage
from autogen_ext.memory.chromadb import (ChromaDBVectorMemory,
    PersistentChromaDBVectorMemoryConfig)
from autogen_ext.memory.canvas import TextCanvasMemory
from chromadb.utils import embedding_functions
import pymupdf
from readability import Document
from pathlib import Path
from typing import Union


def split_text(text: str, chunk_size: int = 500, chunk_overlap: int = 50) -> list[str]:
    """Recursive character splitter.

    Replaces langchain's RecursiveCharacterTextSplitter: langchain-community is
    sunset and warns on import, and all we ever used from it is this split.
    Every returned chunk is at most ``chunk_size`` characters long, and
    consecutive chunks share up to ``chunk_overlap`` trailing characters.
    """
    if chunk_size <= 0:
        raise ValueError("chunk_size must be positive")
    overlap = max(0, min(chunk_overlap, chunk_size - 1))

    def hard_split(piece: str) -> list[str]:
        out, start = [], 0
        while start < len(piece):
            end = min(start + chunk_size, len(piece))
            out.append(piece[start:end])
            if end == len(piece):
                break
            start = end - overlap
        return out

    def recursive(piece: str, separators: list[str]) -> list[str]:
        if len(piece) <= chunk_size:
            return [piece]
        for index, sep in enumerate(separators):
            if sep == "" or sep not in piece:
                continue
            merged, buffer = [], ""
            for part in piece.split(sep):
                candidate = buffer + sep + part if buffer else part
                if len(candidate) <= chunk_size:
                    buffer = candidate
                else:
                    if buffer:
                        merged.append(buffer)
                    buffer = part
            if buffer:
                merged.append(buffer)
            out = []
            for chunk in merged:
                if len(chunk) > chunk_size:
                    out.extend(recursive(chunk, separators[index + 1:]))
                else:
                    out.append(chunk)
            return out
        return hard_split(piece)

    return [c.strip() for c in recursive(text, ["\n\n", "\n", " ", ""]) if c.strip()]

def _read_pdf(path: str) -> list[str]:
    with pymupdf.open(path) as doc:
        return [page.get_text() for page in doc]


def _read_docx(path: str) -> list[str]:
    """Minimal OOXML text extraction - no external dependency needed."""
    ns = "{http://www.w3.org/2001/wordprocessingml/2006/main}"
    with zipfile.ZipFile(path) as zf:
        xml = zf.read("word/document.xml").decode("utf-8", errors="ignore")
    root = ET.fromstring(xml)
    paragraphs = []
    for para in root.iter(f"{ns}p"):
        text = "".join(t.text or "" for t in para.iter(f"{ns}t"))
        if text.strip():
            paragraphs.append(text)
    return paragraphs


class TemplateSafeChromaDBVectorMemory(ChromaDBVectorMemory):
    """ChromaDB memory that injects retrieved context as a UserMessage.

    The base implementation appends a SystemMessage at the END of the model
    context; llama.cpp-based backends (e.g. LM Studio) reject requests where a
    system message is not first ("System message must be at the beginning"),
    which would crash every memory-bearing agent turn on those backends.
    """

    async def update_context(self, model_context: ChatCompletionContext) -> UpdateContextResult:
        messages = await model_context.get_messages()
        if not messages:
            return UpdateContextResult(memories=MemoryQueryResult(results=[]))

        last_message = messages[-1]
        query_text = last_message.content if isinstance(last_message.content, str) else str(last_message)
        query_results = await self.query(query_text)

        if query_results.results:
            memory_strings = [f"{i}. {str(memory.content)}" for i, memory in enumerate(query_results.results, 1)]
            memory_context = "\nRelevant reference material from the knowledge base:\n" + "\n".join(memory_strings)
            await model_context.add_message(UserMessage(content=memory_context, source="memory"))

        return UpdateContextResult(memories=query_results)


class TemplateSafeTextCanvasMemory(TextCanvasMemory):
    """Text canvas memory that injects snapshots as a UserMessage (see above)."""

    async def update_context(self, model_context: ChatCompletionContext) -> UpdateContextResult:
        snapshot = self.canvas.get_all_contents_for_context()
        if snapshot.strip():
            await model_context.add_message(UserMessage(content=snapshot, source="memory"))
            memory_content = MemoryContent(content=snapshot, mime_type=MemoryMimeType.TEXT)
            return UpdateContextResult(memories=MemoryQueryResult(results=[memory_content]))

        return UpdateContextResult(memories=MemoryQueryResult(results=[]))


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
    # Using a specific Sentence Transformer model. The template-safe subclass
    # injects retrieved context as a UserMessage so llama.cpp backends (LM
    # Studio) don't reject the request ("System message must be at the beginning").
    vector_memory = TemplateSafeChromaDBVectorMemory(
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
    total_chunks = 0
    for file_name in os.listdir(docs_dir):
        file_path = os.path.join(docs_dir, file_name)
        ext = os.path.splitext(file_name)[-1].lower()

        try:
            if ext == ".pdf":
                pages = _read_pdf(file_path)
            elif ext == ".txt":
                pages = [Path(file_path).read_text(encoding="utf-8", errors="ignore")]
            elif ext in (".doc", ".docx"):
                pages = _read_docx(file_path)
            else:
                print(f"Unsupported file format: {file_name}")
                continue

            chunks = []
            for page in pages:
                chunks.extend(split_text(page, chunk_size, chunk_overlap))

            for i, chunk in enumerate(chunks):
                await doc_vector_memory.add(
                    MemoryContent(
                        content=chunk,
                        mime_type=MemoryMimeType.TEXT,
                        metadata={"source": file_name, "chunk_index": i}
                    )
                )

            total_chunks += len(chunks)
            print(f"Indexed {len(chunks)} chunks from {file_name}.")

        except (FileNotFoundError, ValueError, RuntimeError, zipfile.BadZipFile) as e:
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
            async with httpx.AsyncClient(follow_redirects=True, timeout=30.0) as client:
                response = await client.get(url, headers={"User-Agent": os.getenv("USER_AGENT", "Mozilla/5.0 (compatible; TFM-BA-GPT/1.0)")})
                response.raise_for_status()
                pages = [response.text]

            for raw_html in pages:

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

def load_config(yaml_path):
    with open(yaml_path, "r") as f:
        return yaml.safe_load(f)


_PROJECT_ROOT = Path(__file__).resolve().parent.parent


def _project_relative(path: str) -> str:
    """Resolve a config path against the project root instead of the CWD."""
    if os.path.isabs(path):
        return path
    return str((_PROJECT_ROOT / path).resolve())


async def rag_indexer_runner(config_path):
    # Load config
    config = load_config(config_path)
    CHROMA_DIR = _project_relative(config["CHROMA_DIR"])
    DOCS_DIR = _project_relative(config["DOCS_DIR"])
    COLLECTION_NAME = config["COLLECTION_NAME"]
    STATE_FILE = _project_relative(config["STATE_FILE"])
    SITES = config["SITES"]

    state = load_index_state(STATE_FILE)
    already_indexed_files = set(state.get("indexed_files", []))
    already_indexed_urls = set(state.get("indexed_urls", []))

    vector_memory = await create_chromadb_memory(CHROMA_DIR, COLLECTION_NAME)

    # --- Find all files in DOCS_DIR
    docs_path = Path(DOCS_DIR)
    if not docs_path.exists():
        print(f"⚠️  Documents directory not found: {DOCS_DIR} — skipping local document indexing.")
        all_files = set()
    else:
        all_files = {
            str(f.relative_to(DOCS_DIR)) for f in docs_path.rglob("*")
            if f.is_file() and f.suffix.lower() in {".pdf", ".docx", ".txt"}
        }

    new_files = all_files - already_indexed_files
    new_urls = set(SITES) - already_indexed_urls

    if new_files or new_urls:
        print("🔄 Indexing new content...")

        # Documents
        if new_files:
            print(f"📄 Found {len(new_files)} new documents.")
            await load_and_index_documents(DOCS_DIR, vector_memory)
            state["indexed_files"] = sorted(list(all_files))
            print(f"✅ Indexed documents in {DOCS_DIR}.")

        # URLs
        if new_urls:
            print(f"🌐 Found {len(new_urls)} new URLs.")
            await load_and_index_web_page(list(new_urls), vector_memory)
            state["indexed_urls"] = sorted(list(already_indexed_urls.union(new_urls)))
            print("✅ Indexed web pages.")

        save_index_state(state, STATE_FILE)
    else:
        print("✅ All documents and URLs are already indexed.")
    return vector_memory
