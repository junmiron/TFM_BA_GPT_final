"""
This module provides agent tools.
"""
import os
import json
from datetime import datetime

DEFAULT_JSONL_PATH = "../conversation/interview.jsonl"
DEFAULT_MD_PATH = "../conversation/final_summary.md"
DEFAULT_MD_SPEC_PATH = "../conversation/functional_specification.md"
DEFAULT_MERMAID_PATH = "../conversation/process_diagram.mmd"

def write_mermaid_to_file_tool(mermaid_code: str, file_path: str = DEFAULT_MERMAID_PATH) -> str:
    """
    Writes Mermaid diagram code to a .mmd file with proper formatting.

    Args:
        mermaid_code (str): The Mermaid syntax/code to write.
        file_path (str): Optional path for saving. Defaults to DEFAULT_MERMAID_PATH.

    Returns:
        str: Confirmation or error message.
    """
    import os
    try:
        # Ensure the folder exists
        os.makedirs(os.path.dirname(file_path), exist_ok=True)

        # Validate file extension
        if not file_path.endswith('.mmd'):
            return "Error: Filename must end with '.mmd'"

        # Write the Mermaid code into a fenced code block
        with open(file_path, 'w', encoding='utf-8') as file:
            file.write("```mermaid\n")
            file.write(mermaid_code)
            file.write("\n```")

        return f"Mermaid diagram successfully written to {file_path}"
    except Exception as e:
        return f"Error writing Mermaid file: {e}"


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


def write_md_file_tool(content: str, file_path: str = DEFAULT_MD_SPEC_PATH) -> str:
    """
    Writes the functional specification to a Markdown file.
    """
    try:
        os.makedirs(os.path.dirname(file_path), exist_ok=True)
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(content)
        return f"Markdown spec successfully written to {file_path}"
    except Exception as e:
        return f"Error writing Markdown spec: {e}"

def read_md_file_tool(file_path: str = DEFAULT_MD_SPEC_PATH) -> str:
    """
    Reads the entire content of a Markdown file and returns it as a string.

    Args:
        file_path (str): Optional path to the Markdown spec (defaults to DEFAULT_MD_SPEC_PATH).

    Returns:
        str: The full text content of the Markdown file, or an error message.
    """
    import os
    try:
        if not os.path.exists(file_path):
            return f"Error: Markdown file not found at {file_path}"

        with open(file_path, 'r', encoding='utf-8') as f:
            content = f.read()

        return content if content.strip() else "Markdown file is empty — no readable text found."
    except Exception as e:
        return f"Error reading Markdown file: {e}"