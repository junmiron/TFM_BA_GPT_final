import os
import sys
import asyncio
import json
from pathlib import Path

# --- CONFIG PATHS (define these before anything else uses them) ---
CHROMA_DIR = "../chromadb_storage"
DOCS_DIR = "../data"
COLLECTION_NAME = "rag_collection"
STATE_FILE = "../index_state.json"

SITES = [
    "https://www.morebusiness.com/business-analyst-interview-questions/",
    "https://ellogy.ai/comprehensive-guide-asking-the-right-questions-in-it-requirements-gathering/",
    "https://medium.com/@alishadhillon__/typical-requirements-gathering-questions-in-a-data-viz-project-fa7c04f0b2ad",
    "https://www.requiment.com/the-most-asked-questions-about-requirements-gathering/",
    "https://practicalanalyst.com/requirements-elicitation-most-valuable-questions/",
    "https://www.modernanalyst.com/Resources/Articles/tabid/115/ID/179/8-Questions-Every-Business-Analyst-Should-Ask.aspx",
    "https://www.thenarratologist.com/best-business-analyst-questions-to-gather-requirements/",
    "https://www.requiment.com/business-analyst-requirements-gathering-interview-questions-answers/",
]

# --- PATH FIX FOR IMPORTS ---
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from lib.rag_helpers import (
    create_chromadb_memory,
    load_and_index_documents,
    load_and_index_web_page,
    load_index_state,
    save_index_state,
)


async def main():
    state = load_index_state(STATE_FILE)
    already_indexed_files = set(state.get("indexed_files", []))
    already_indexed_urls = set(state.get("indexed_urls", []))

    vector_memory = await create_chromadb_memory(CHROMA_DIR, COLLECTION_NAME)

    # --- Find all files in DOCS_DIR
    all_files = {
        str(f.relative_to(DOCS_DIR)) for f in Path(DOCS_DIR).rglob("*")
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


if __name__ == "__main__":
    asyncio.run(main())

