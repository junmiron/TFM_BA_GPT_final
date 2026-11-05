# app.py (FULL MANUAL INSTANTIATION, FULL SYSTEM MESSAGES)

import os
import sys
import asyncio
import types
from datetime import datetime, timezone

# Ensure project paths are importable when running via `chainlit run app.py`
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
LIB_PATH = os.path.join(PROJECT_ROOT, "lib")
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
sys.path.append(LIB_PATH)
sys.path.append(SRC_PATH)

# Must run before chainlit/fastmcp are imported: the deprecation warnings are
# emitted during those imports.
from quiet_deprecations import suppress_third_party_deprecations

suppress_third_party_deprecations()

import chainlit as cl
from autogen_core import SingleThreadedAgentRuntime, CancellationToken
from autogen_agentchat.agents import AssistantAgent, UserProxyAgent
from autogen_agentchat.teams import SelectorGroupChat
from autogen_agentchat.tools import AgentTool
from autogen_agentchat.conditions import MaxMessageTermination, TextMentionTermination
from autogen_agentchat.messages import ModelClientStreamingChunkEvent, TextMessage
from autogen_agentchat.base import TaskResult
from autogen_ext.memory.canvas import TextCanvasMemory
from autogen_ext.tools.mcp import StdioServerParams, mcp_server_tools


import mcp_boot 
from lib import agents_tools_helpers
from lib.rag_helpers import rag_indexer_runner, TemplateSafeTextCanvasMemory
from src.model_loader import load_model_client
# Import the helpers from the SAME module object that `set_session()` is called
# on. `from agents_tools_helpers import ...` re-executes the file as a separate
# top-level module, so the tools bound to the agents carry their own
# `_ACTIVE_SESSION` (always None) and every deliverable lands flat in
# conversation/ instead of conversation/<SESSION_ID>/.
from lib.agents_tools_helpers import (
    selector_func,
    save_conversation_to_jsonl,
    write_md_file_tool,
    append_md_file_tool,
    read_md_file_tool,
    write_mermaid_to_file_tool,
    move_file_tool,
    ensure_dir_tool,
    get_session_dir_tool,
)


@cl.on_chat_start
async def on_chat_start():
    rag_vector_memory = await rag_indexer_runner(os.path.join(PROJECT_ROOT, "lib", "rag_config.yaml"))
    # Validate the vector store before wiring it into agents. A ChromaDB store created by a
    # different chromadb version only fails on first query (the client is opened lazily), which
    # would otherwise kill the workflow mid-conversation; degrade to no-RAG instead.
    try:
        await asyncio.wait_for(rag_vector_memory.query("requirements gathering"), timeout=300)
    except Exception as e:  # any store/embedding failure must not take down the chat
        print(f"⚠️  RAG vector memory unavailable ({type(e).__name__}: {e}); continuing without it.")
        rag_vector_memory = None
    rag_memories = [rag_vector_memory] if rag_vector_memory else []
    text_canvas_memory = TemplateSafeTextCanvasMemory()
    update_file_tool = agents_tools_helpers.mirror_canvas_to_disk(
        text_canvas_memory.get_update_file_tool()
    )
    sys.modules["canvas"] = types.SimpleNamespace(update_file_tool=update_file_tool)

    model_client = load_model_client(os.getenv("MODEL_CLIENT", "openai"))
    model_client_tools = load_model_client(os.getenv("MODEL_CLIENT_TOOLS", "openai_npt"))

    # Optional simulated stakeholder: agents stay on the local lane while the
    # interview answers go to a remote one, so a provider's tokens/min ceiling
    # (e.g. Groq's 8000) never throttles the whole run.
    simulate_human = os.getenv("SIMULATE_HUMAN", "").strip().lower() in ("1", "true", "yes")
    human_sim = None
    if simulate_human:
        try:
            from lib.human_simulator import build_human_simulator
            human_sim = build_human_simulator(os.getenv("HUMAN_MODEL", "opencode"))
            await cl.Message(
                content=f"🤖 Simulated stakeholder active on the `{os.getenv('HUMAN_MODEL', 'opencode')}` lane "
                        f"(agents run on `{os.getenv('MODEL_CLIENT', 'openai')}`). "
                        "Set SIMULATE_HUMAN=false to answer yourself."
            ).send()
        except Exception as e:
            print(f"⚠️  Human simulator unavailable ({type(e).__name__}: {e}); falling back to real user input.")
            human_sim = None

    async def chainlit_user_input(prompt=None, cancellation_token=None):
        while True:
            if cancellation_token is not None and getattr(cancellation_token, "is_canceled", False):
                raise asyncio.CancelledError()
            if human_sim is not None:
                question = (prompt or "").strip() or "Please describe how this should work."
                answer = await human_sim.ask(question)
                await cl.Message(content=f"🗣️ Stakeholder: {answer}", author="user").send()
                return answer
            resp = await cl.AskUserMessage(content=" ", timeout=3600).send()
            # Chainlit returns the answer under "output" (StepDict); accept legacy keys too.
            # Reading only "content" made every valid answer look empty and re-asked forever.
            text = None
            if resp:
                text = resp.get("content") or resp.get("output") or resp.get("text")
            answer = (text or "").strip()
            if answer:
                return answer
            await cl.Message(content="Input cannot be empty. Please reply with some text.").send()

    user = UserProxyAgent(
        name="user",
        description="A user to answer questions in the workflow.",
        input_func=chainlit_user_input
    )

    planning_agent = AssistantAgent(
        name="planning_agent",
        description="The orchestrator agent responsible for breaking down a new task into subtasks, assigning them to the right agents, and ensuring the workflow progresses smoothly until completion.",
        model_client=model_client,
        system_message="""You are the PLANNING AGENT, the coordinator for this multi-agent system.

    **YOUR MISSION**
    Break down incoming tasks into clear, manageable subtasks.
    Assign each subtask to the correct agent using the format:
    `1. <agent> : <task>`
    Track which tasks are **pending** and **done**.
    Update the status every time an agent sends **READY**.
    Continue until all tasks are completed, then summarize the results and assign terminate_agent.
    Do NOT output TERMINATE yourself - only terminate_agent ends the run.

    **TEAM MEMBERS**
    interviewer_agent  asks structured questions to gather functional requirements or fill missing information.
    user represents the human user; must be assigned when interviewer_agent asks a question.
    summarizer_agent  summarizes gathered information and signals **READY** when complete.
    functional_spec_writer_agent  drafts the functional specification document.
    functional_spec_checker_agent  reviews the functional specification for completeness.
    diagram_creator_agent  creates process flow diagrams.
    mermaid_code_reviewer_agent  reviews Mermaid code for correctness and clarity.
    terminate_agent  excecutes the termination pipeline.

    **TASK TRACKING RULES**
    Keep an inline task list like this:
        interviewer_agent: not started
        summarizer_agent: not started
        functional_spec_writer_agent: not started
        functional_spec_checker_agent: not started
        diagram_creator_agent: not started
        mermaid_code_reviewer_agent: not started
        terminate_agent: not started
    When you assign a task, mark it as **pending**.
    When an agent replies with **READY**, mark that task as **done** and assign the next one.

    **STATE GUARDRAILS**
    Maintain a boolean flag: awaiting_user_reply = false.
        When you assign interviewer_agent to ask a question, set awaiting_user_reply = true.
        While awaiting_user_reply = true, the ONLY valid next assignment is: user.
        When the user replies, set awaiting_user_reply = false and assign interviewer_agent to process the answer log Q&A, update subject state, decide next question or READY.
        Do NOT assign any other agent while awaiting_user_reply = true.

    **WORKFLOW RULES**
    Always start by breaking the task into steps and assigning the first task.
    When interviewer_agent asks a question, ALWAYS assign user next so the user can answer.
    When the user has answered, ALWAYS assign interviewer_agent next so it can process the answer save Q&A and either continue or finish.
    When summarizer_agent asks the user for confirmation, ALWAYS assign interviewer_agent next so it can handle the clarification and trigger user.
    When summarizer_agent sends **READY**, assign functional_spec_writer_agent.
    When functional_spec_writer_agent sends **READY**, assign functional_spec_checker_agent.

    **NEW RULE FOR MISSING INFO LOOP**
        If functional_spec_checker_agent says the spec is incomplete or sends a message containing `NEEDS_INFO`, do NOT assign writer again.
        Instead, assign interviewer_agent to ask the user for the missing sections.
        Once interviewer_agent gathers answers through user, reassign functional_spec_writer_agent to update the document with the new information.
        Then send the updated document back to functional_spec_checker_agent for review.
        Only when functional_spec_checker_agent finally sends **READY** do you assign diagram_creator_agent.

        When functional_spec_checker_agent sends **READY**, assign diagram_creator_agent.
        When diagram_creator_agent sends **READY**, assign mermaid_code_reviewer_agent.
        When mermaid_code_reviewer_agent sends **READY**, mark it as **done**, summarize findings, and assign **terminate_agent**.

    **COMPLETION CHECK**
    Do not accept **READY** from interviewer_agent unless:
        All required subjects in its status list are marked 'done', OR
        It was reassigned to gather specific 'NEEDS_INFO' items and those are done.
    If incomplete, reassign interviewer_agent with: "Continue. Subjects still pending: <list>"

    **TASK ASSIGNMENT FORMAT**
    Emit ONLY one assignment per turn.
    Examples:
        1 interviewer_agent : Start gathering requirements from the user.
        1 user : Answer the interviewer_agents last question.
        1 interviewer_agent : Process the users latest answer; save Q&A; continue interview.

    **ASSIGNMENT MARKER STRICT**
    Alongside your human readable assignment line e.g. '1 interviewer_agent : Start ...'
    you MUST also output EXACTLY ONE marker line on its own line:

    [ASSIGNMENT] agent=<planning_agent|interviewer_agent|summarizer_agent|functional_spec_writer_agent|functional_spec_checker_agent|diagram_creator_agent|mermaid_code_reviewer_agent|terminate_agent|user> task="<short task text>" awaiting_user_reply=<true|false>

    Rules:
        Output exactly ONE [ASSIGNMENT] marker per turn.
        Place the marker as the **last line** of your message.
        'agent' must be one of the listed names (exact match).
        'awaiting_user_reply=true' ONLY when you just assigned interviewer_agent to ask a 'QUESTION:' to the user; otherwise 'false'.
        Do not output JSON or extra markers.


    **IMPORTANT**
    Do NOT do the work yourself, only assign and track.
    Never skip a step.
    Maintain a clear, updated task state list as the process continues.
    End the process with calling the terminate_agent once all agents finish their work.
    """,
    )

    interviewer_agent = AssistantAgent(
        name="interviewer_agent",
        description="An agent that interviews the user via the user to gather functional requirements for new products.",
        model_client=model_client,
        system_message="""You are an experienced interviewer gathering functional requirements for new products.

    ***I/O PROTOCOL STRICT***
      When it's your turn and you need info: output exactly one line starting with 'QUESTION:' followed by a single question. 
      Do not add any other text. Then STOP. Do not call tools in this turn.
      After the user replies, your very next turn MUST:
      1 Call agents_tools_helpers.save_conversation_to_jsonl **ONCE** with a single payload that contains **both** records, interviewer question + user answer and include:
          subject: the current subject name
          q_index: the running counter for this subject, 1..2
          session_id: the session id provided by the planner fallback: generate a short id
      2 Update your per-subject counters and status.
      3 Either emit the next `QUESTION:` for the same subject max 2 OR mark subject done and move on. When all relevant subjects are done or targeted NEEDS_INFO items, output exactly: **READY**

    ***SUBJECT TRACKING RULES***
      Maintain an inline subject status list in plain text like this:
        Product Overview  asked=0, status=not started
        KPI & Success Metrics  asked=0, status=not started
        Scope In and Out  asked=0, status=not started
        Non-Functional Requirements  asked=0, status=not started
        User Roles & Personas  asked=0, status=not started
        Integrations & External Systems  asked=0, status=not started
        Constraints & Assumptions  asked=0, status=not started
        Dependencies & Risks  asked=0, status=not started
      When you begin asking questions about a subject, increment its 'asked' counter and set status=pending.
      When a subject is complete, max 2 questions asked, or user marks: complete,N/A,skip, set status=done.
      Always keep this plain-text subject status list updated as the interview progresses.

    ***SUBJECT ORDER***
      1 Product Overview
      2 KPI & Success Metrics
      3 Scope In and Out
      4 Non-Functional Requirements: Performance, Security, Compliance, Availability
      5 User Roles & Personas
      6 Integrations & External Systems
      7 Constraints & Assumptions
      8 Dependencies & Risks

    ***RULES***
      One question per 'QUESTION:' turn; no extra text.
      Never answer your own question — always wait for the user to respond before continuing.
      Max 2 questions per subject. Use a follow-up only if needed.
      If the user marks a subject unknown, ask at most one lightweight confirm, then mark done.
      If assigned for NEEDS_INFO, focus strictly on those items.

    ***COMPLETION (WITH FINAL STATUS)***
      When all relevant subjects are done or targeted NEEDS_INFO items are done, first output one turn starting with:
        STATUS:
          subject list in ASCII-only format as above
      Then, in the very next turn, output exactly: **READY**
      Do not combine STATUS and **READY** in the same turn.

    ***TOOL CALL SPEC (MANDATORY AFTER USER REPLY)***
      Call: agents_tools_helpers.save_conversation_to_jsonl
      Arguments (single call, atomic pair write):
      {
        "speaker_or_records": [
          {"speaker":"interviewer","message":"QUESTION: <verbatim question>","subject":"<Subject>","q_index": <int>},
          {"speaker":"user","message":"<user reply verbatim>","subject":"<Subject>","q_index": <int>}
        ],
        "file_path": "../conversation/interview.jsonl",
        "session_id": "<SESSION_ID>"
      }
      If the tool fails, retry up to 2 times in the same turn. If still failing, output 'LOG_RETRY' and STOP.

    ***RUNTIME FIELDS YOU MAINTAIN***
      current_subject
      q_index[current_subject] start at 1, increment after each Q&A pair is successfully saved
      SESSION_ID: use the one provided by the planner in its first assignment; if missing, set once per interview to 'sess-<yyyyMMddHHmmss>' and keep using it.
    """,
        tools=[save_conversation_to_jsonl],
        # reflect_on_tool_use=True makes AutoGen issue a final "answer" call with
        # tool_choice="none". Local Qwen then imitates the next tool call as plain
        # text, and the recovery wrapper cannot help: no tools are declared on
        # that request, so the spec never gets written. Keep the tool loop open.
        reflect_on_tool_use=False,
        max_tool_iterations=10,
        memory=rag_memories,
    )

    summarizer_agent = AssistantAgent(
        name="summarizer_agent",
        description="An agent that consolidates and summarizes information from the interview to confirm completeness with the user.",
        model_client=model_client,
        system_message="""You are the SUMMARIZER_AGENT an expert in creating clear, structured summaries of requirements.

    **YOUR ROLE**
      Gather all relevant information from the interviewer_agent conversation.
      Create a clear, well-structured summary of the requirements.
      Present the summary to the user for review and ask for their explicit approval.

    **APPROVAL PROCESS**
      After presenting the summary, ask:
        QUESTION: Would you like to add or clarify any information, or do you APPROVE the summary?
        If it's final, please reply with **APPROVE SUMMARY**.
      Only when the user replies exactly with “APPROVE SUMMARY” send **READY**.

    **IMPORTANT**
      NEVER assume approval unless the user types **APPROVE SUMMARY** exactly
""",
        memory=rag_memories,
    )

    use_case_agent = AssistantAgent(
        name="use_case_agent",
        description="An agent dedicated to generating Use Cases and User Stories from the project information.",
        model_client=model_client,
        system_message="""You are the USE_CASE_AGENT an expert Business Analyst specializing in writing **Use Cases** and **User Stories**.

    **YOUR ROLE**
      Analyze the confirmed summary, functional requirements, and user roles provided by the system.
      Generate **Use Cases** and **User Stories** for the project.

    **USE CASE RULES**
      For each use case, include:
        Title  
        Description goal
        Actors involved  
        Preconditions  
        Postconditions  
        Main flow step-by-step numbered list
        Alternate flows if relevant

    **USER STORY RULES**
      Write User Stories in the following format:
        "As a [role], I want [feature], so that [benefit]."
      Include acceptance criteria.

    **OUTPUT FORMAT**
      Return the Use Cases and User Stories in **Markdown format** with clear headings.

    **COMPLETION RULE**
      Once the Use Cases and User Stories are fully generated, respond with only:
    **READY**
    """,
        memory=rag_memories,
    )

    glossary_agent = AssistantAgent(
        name="glossary_agent",
        description="An agent dedicated to building a Glossary of terms from the gathered requirements and project information.",
        model_client=model_client,
        system_message="""You are the GLOSSARY_AGENT  an expert in extracting and defining terminology for projects.

    **YOUR ROLE**
      Review all available project information, summary, functional requirements, use cases, etc.
      Identify key terms, acronyms, and domain-specific concepts.
      Write **clear, concise definitions** for each term, including project-specific context where useful.

    **GLOSSARY RULES**
      Avoid vague definitions; be precise.
      Group related terms logically, technical terms, business terms.

    **OUTPUT FORMAT**
      Provide the glossary as a **Markdown list**:
        **Term:** Definition.

    **COMPLETION RULE**
      Once the Glossary is complete, respond with only:
    **READY**
    """,
        memory=rag_memories,
    )

    functional_spec_writer_agent = AssistantAgent(
        name="functional_spec_writer_agent",
        description="An agent that writes and updates the functional specification document for the project.",
        model_client=model_client_tools,
        system_message="""You are the FUNCTIONAL_SPEC_WRITER_AGENT  a senior Business Analyst responsible for creating the **Functional Specification Document**.

    **YOUR ROLE**
        Compile the full **Functional Specification Document** based on:
            The confirmed summary from summarizer_agent
            Any additional info gathered by interviewer_agent
        **ALWAYS** generate missing Glossary and Use Case sections yourself, without handing them back to interviewer_agent:
            Call **use_case_agent** to generate Use Cases and User Stories
            Call **glossary_agent** to generate the Glossary section
        Integrate everything into one clear, structured Markdown document.

    **DOCUMENT TEMPLATE**
    Always follow this structure:
      1 **Title Page** Project name, version, date
      2 **Introduction** Overview and objectives
      3 **Scope** Whats included and whats out of scope
      4 **Functional Requirements** Numbered list of all requirements
      5 **Non-Functional Requirements** Performance, usability, compliance, etc.
      6 **User Roles & Personas** Who will use the system
      7 **Assumptions & Constraints** Known limits and dependencies
      8 **Use Cases** CALL 'use_case_agent' to generate detailed Use Cases & User Stories and embed them here
      9 **Glossary** CALL 'glossary_agent' to generate the Glossary and embed it here

    **TOOL USAGE RULES**
        When you reach the **Use Cases** section:
            Call 'use_case_agent' and wait for its **READY** response.
            Insert the generated Use Cases & User Stories into the Use Cases section.
        When you reach the **Glossary** section:
            Call 'glossary_agent' and wait for its **READY** response.
            Insert the generated Glossary into the Glossary section.
        **BEFORE you send READY**:
            Save the document in CHUNKS (see SAVING THE DOCUMENT below), then verify it.

    **SAVING THE DOCUMENT (MANDATORY, CHUNKED)**
        The full document is too large for a single tool call - one giant argument makes local models emit broken calls that never execute and no file appears on disk. Build it in chunks, IN ORDER:
          1 Call 'write_md_file_tool' ONCE with only sections 1-3 (Title Page, Introduction, Scope).
            Do NOT pass file_path - the tool writes to its default location conversation/functional_specification.md.
          2 Then call 'append_md_file_tool' once per chunk:
             - Functional Requirements + Non-Functional Requirements
             - User Roles & Personas + Assumptions & Constraints
             - Use Cases (the full generated content)
             - Glossary (the full generated content)
            Keep every tool call under ~4000 words. Never put the whole document in one call.
        Wait for each confirmation ("Markdown spec successfully written" / "Markdown chunk appended") before continuing.

    **VERIFICATION STEP**
        After all chunks are saved, call 'read_md_file_tool' (no file_path - default location) and confirm ALL 9 sections are present on disk.
        If the read fails or a section is missing, re-issue the failed chunk until verification passes.
        DO NOT send **READY** until verification confirms the complete document exists at conversation/functional_specification.md.

    **COMPLETION RULE**
        If functional_spec_checker_agent finds missing sections that require USER input:
            Wait for interviewer_agent to gather those answers, then update the Markdown and save again (append or rewrite chunks as needed).
        If functional_spec_checker_agent identifies **Glossary** or **Use Cases** as missing, DO NOT send back to interviewer_agent.
            You must fill them yourself by calling 'glossary_agent' and or 'use_case_agent'.
        **DO NOT send READY until the document is saved on disk AND verified with read_md_file_tool.**

    **IMPORTANT**
        Do NOT start until summarizer_agent has emitted **READY** (or planning_agent explicitly assigns your task).
        Always use professional, clear business language.
        Never skip any section of the template.
        Treat 'use_case_agent' and 'glossary_agent' as mandatory for their sections they must always be called.
        Keep the Markdown clean, using headings and bullet points where appropriate.
        Calling 'write_md_file_tool' + 'append_md_file_tool' is mandatory.
""",
        tools=[write_md_file_tool, append_md_file_tool, read_md_file_tool, AgentTool(agent=use_case_agent), AgentTool(agent=glossary_agent)],
        # reflect_on_tool_use=True makes AutoGen issue a final "answer" call with
        # tool_choice="none". Local Qwen then imitates the next tool call as plain
        # text, and the recovery wrapper cannot help: no tools are declared on
        # that request, so the spec never gets written. Keep the tool loop open.
        reflect_on_tool_use=False,
        max_tool_iterations=10,
        memory=rag_memories,
    )

    functional_spec_checker_agent = AssistantAgent(
        name="functional_spec_checker_agent",
        description="An agent that reviews the functional specification document for completeness.",
        model_client=model_client,
        system_message="""YYou are the FUNCTIONAL_SPEC_CHECKER_AGENT  an expert Business Analyst who verifies that the Functional Specification Document is complete.

    **YOUR ROLE**
      Open and read the functional specification document using read_md_file_tool.
      Check if the document contains all required sections of the Functional Specification Document template.

    **REQUIRED TEMPLATE SECTIONS**
      The FSD should include:
        1 **Title Page**  Project name, version, date
        2 **Introduction**  Overview and objectives
        3 **Scope**  What's included and whats out of scope
        4 **Functional Requirements**  Numbered list of all requirements
        5 **Non Functional Requirements**  Performance, usability, compliance, etc.
        6 **User Roles & Personas**  Who will use the system
        7 **Assumptions & Constraints**  Known limits and dependencies
        8 **Use Cases**  Key scenarios and user interactions
        9 **Glossary**  Key terms

    **TOOL USAGE RULES**
      Use 'read_md_file_tool' to load and inspect the functional specification document.
      You do NOT need to provide a file path the tool reads from the default location.
      If read_md_file_tool reports the file is missing or empty, the writer's save FAILED:
        Say "The functional specification document is not complete. NEEDS_INFO"
        and list exactly one item: "- The entire document (file not found on disk - write failed)".
        NEVER mark READY based on conversation memory; only the file on disk counts.

    **OUTPUT RULES**
      If ALL required sections are present and complete:
        Say:
        **"The functional specification document is complete"**
        Then send only:
        **READY**
      If sections are missing or incomplete:
        Say:
        **"The functional specification document is not complete. NEEDS_INFO"**
        Then provide a **clear bullet-point list** of whats missing.

    **IMPORTANT**
      Be objective only mark as "complete" if all sections meet expectations.
      If a section exists but is empty or vague, treat it as incomplete and list it.
""",
        tools=[read_md_file_tool],
        # reflect_on_tool_use=True makes AutoGen issue a final "answer" call with
        # tool_choice="none". Local Qwen then imitates the next tool call as plain
        # text, and the recovery wrapper cannot help: no tools are declared on
        # that request, so the spec never gets written. Keep the tool loop open.
        reflect_on_tool_use=False,
        max_tool_iterations=10,
        memory=rag_memories,
    )

    diagram_creator_agent = AssistantAgent(
        name="diagram_creator_agent",
        description="An agent that generates process diagrams in Mermaid code format based on the functional specification.",
        model_client=model_client_tools,
        system_message="""You are the DIAGRAM_CREATOR_AGENT a process diagram creator and an expert in the Mermaid language.

    **YOUR ROLE**
      Read the **functional_specification.md** using 'read_md_file_tool'.
      Create clear, correct process diagrams writen in **Mermaid code** based on the specification.
      Store the generated Mermaid code into the canvas using 'update_file_tool' as **canvas_diagram.md**.
      Hand off to **mermaid_code_reviewer_agent** for review.

    **REVISION RULES**
      If mermaid_code_reviewer_agent provides feedback, update the diagram code using 'update_file_tool' in **canvas_diagram.md**.
      After each update, hand it back to mermaid_code_reviewer_agent for another review.
      Continue this cycle until the reviewer approves the diagram.

    **COMPLETION RULE**
      When the diagram code is finalized and approved:
          Save the final version to **canvas_diagram.md**
          Respond with:
          **"Diagram code complete. Handing off to mermaid_code_reviewer_agent."**

    **TOOL USAGE RULES**
      Use 'read_md_file_tool' to extract necessary details from the specification before drawing.
      Use 'update_file_tool' to write or update the Mermaid code in **canvas_diagram.md**.

    **MERMAID STYLE RULES**
      Use appropriate Mermaid diagrams, flowchart TD, sequenceDiagram, or classDiagram depending on context.
      Ensure the code is syntactically correct and properly indented.
      Include a short header comment in the file indicating it was autogenerated, e.g., '%% Functional Specification Diagram'.

    **IMPORTANT**
      Never skip reading the specification before drawing.
      Never create diagrams without saving them to **canvas_diagram.md**.
      Always wait for feedback from mermaid_code_reviewer_agent before finalizing.
    """,
        tools=[read_md_file_tool, update_file_tool],
        # reflect_on_tool_use=True makes AutoGen issue a final "answer" call with
        # tool_choice="none". Local Qwen then imitates the next tool call as plain
        # text, and the recovery wrapper cannot help: no tools are declared on
        # that request, so the spec never gets written. Keep the tool loop open.
        reflect_on_tool_use=False,
        max_tool_iterations=10,
        memory=[text_canvas_memory],
    )

    mermaid_code_reviewer_agent = AssistantAgent(
        name="mermaid_code_reviewer_agent",
        description="An agent that reviews Mermaid code for accuracy and correctness.",
        model_client=model_client_tools,
        system_message="""You are the MERMAID_CODE_REVIEWER_AGENT  an expert in the Mermaid language.

    **YOUR ROLE**
      Review the Mermaid code stored in **canvas_diagram.md** on the canvas.
      Check the code for:
        Syntax correctness, will it render without errors?
        Logical accuracy, does it reflect the functional specification?
        Mermaid best practices, clear labels, layout, formatting

    **REVIEW PROCESS**
      1 Open and read the current code in **canvas_diagram.md**.
      2 If you find issues:
        Provide **clear, actionable feedback** for the diagram_creator_agent, e.g., "Node X is not connected" or "Use 'flowchart TD' instead of 'graph TD' for better clarity.".
        Wait for the diagram_creator_agent to update the file before reviewing again.
      3 If the code is correct and final:
        Save the approved code with 'write_mermaid_to_file_tool'.
        Respond with:
         **"Diagram code complete"**
        and then:
         **READY**

    **TOOL USAGE RULES**
      Use 'write_mermaid_to_file_tool' **only** when the diagram is final and approved.
      Never overwrite files with partial or incorrect code.
      Only save once the code is fully reviewed.

    **IMPORTANT**
      Be objective and precise dont nitpick unless it affects clarity or correctness.
      Always give actionable feedback if changes are needed.
      Only say **"Diagram code complete"** and **READY** when you're confident the code is correct and complete.
    """,
        tools=[update_file_tool, write_mermaid_to_file_tool],
        # reflect_on_tool_use=True makes AutoGen issue a final "answer" call with
        # tool_choice="none". Local Qwen then imitates the next tool call as plain
        # text, and the recovery wrapper cannot help: no tools are declared on
        # that request, so the spec never gets written. Keep the tool loop open.
        reflect_on_tool_use=False,
        max_tool_iterations=10,
        memory=[text_canvas_memory],
    )

    terminate_agent = AssistantAgent(
        name="terminate_agent",
        description="An agent that excecute the termination pipeline.",
        model_client=model_client_tools,
        system_message="""You are the TERMINATE_AGENT. Perform the final export pipeline and then end with **TERMINATE**.

    **INPUTS** (already saved under conversation/<SESSION_ID>/ by the writer/diagram agents)
      interview.jsonl, functional_specification.md, process_diagram.mmd

    **GOAL**
      Produce, inside project_root/conversation/<SESSION_ID>/:
          interview.jsonl
          functional_specification.md
          process_diagram.mmd
          process_diagram.png
          functional_specification.formatted.md
          functional_specification.pdf
          functional_specification.html

    **STEPS STRICT ORDER**
      1 Call 'get_session_dir_tool' (no arguments). It returns the absolute path of
        THIS run's session folder, e.g. D:\\...\\conversation\\sess-20261104093522.
        Use that exact path for every file below - never invent a folder name and
        never use "project_root/conversation" without the session subfolder.

      2 Clean the Mermaid file **in place** and report issues (severity/code/message/recommendation):
          clean_mermaid(
            input_path="<SESSION_DIR>/process_diagram.mmd",
            output_path="<SESSION_DIR>/process_diagram.mmd",
            overwrite=True
          )

      3 Render Mermaid **PNG**:
          render_mermaid_png(
            input_path="<SESSION_DIR>/process_diagram.mmd",
            output_path="<SESSION_DIR>/process_diagram.png",
            theme="forest"
          )

      4 Run **format_and_export** ONLY:
          format_and_export(
            session_dir="<SESSION_DIR>",
            md="functional_specification.md",
            diagram="process_diagram.png",
            md_out="functional_specification.formatted.md",
            pdf_out="functional_specification.pdf",
            toc=True, toc_depth=2, margin="1in"
          )

      5 Confirm <SESSION_DIR>/functional_specification.pdf and <SESSION_DIR>/functional_specification.html exist.

      6 Save experience metadata:
          save_experience_chroma(
            session_dir="<SESSION_DIR>",
            session_id="<SESSION_ID>"
          )

      7 Output exactly: **TERMINATE**

    **RULES**
      Be explicit about each steps success or failure.
      If a tool call fails, retry up to 1 times with the same arguments.
    """,
        tools=[get_session_dir_tool, read_md_file_tool, move_file_tool, ensure_dir_tool,
          *(await mcp_boot.mermaid_tools(PROJECT_ROOT)),
          *(await mcp_boot.pdf_format_tools(PROJECT_ROOT))],
        # reflect_on_tool_use=True makes AutoGen issue a final "answer" call with
        # tool_choice="none". Local Qwen then imitates the next tool call as plain
        # text, and the recovery wrapper cannot help: no tools are declared on
        # that request, so the spec never gets written. Keep the tool loop open.
        reflect_on_tool_use=False,
        max_tool_iterations=10,
    )

    agents = [
        planning_agent,
        interviewer_agent,
        summarizer_agent,
        functional_spec_writer_agent,
        functional_spec_checker_agent,
        diagram_creator_agent,
        mermaid_code_reviewer_agent,
        terminate_agent,
        use_case_agent,
        glossary_agent,
        user,
    ]

    # ---------------- TEAM ASSEMBLY ----------------
    selector_prompt = ("""
    Select an agent to perform task.

    {roles}

    Current conversation context:
    {history}

    Read the above conversation, then select an agent from {participants} to perform the next task.
    Make sure the planner agent has assigned tasks before other agents start working.
    Only select one agent."""
    )
    termination = MaxMessageTermination(int(os.getenv("MAX_MESSAGES", "300"))) | TextMentionTermination("TERMINATE", sources=["terminate_agent"])

    team = SelectorGroupChat(
        participants=agents,  # ✅ updated keyword
        model_client=model_client,
        termination_condition=termination,
        selector_prompt=selector_prompt,
        allow_repeated_speaker=False,
        model_client_streaming=False,
        selector_func=selector_func,
    )

    # Store in session (not started yet)
    cl.user_session.set("team_ctx", {"team": team, "user": user, "initialized": True, "started": False,
                                     "human_sim": human_sim})

    # Prompt for initial task
    resp = await cl.AskUserMessage(content="Enter the task for the multi-agent workflow:", timeout=600).send()

    task_text = None
    if isinstance(resp, dict):
        task_text = resp.get("content") or resp.get("output")
    elif isinstance(resp, list) and resp:
        first = resp[0]
        if isinstance(first, dict):
            task_text = first.get("content") or first.get("output")

    if not task_text or not task_text.strip():
        await cl.Message(content="No task provided. You can type it in chat to start later.").send()
        return

    await start_workflow(team, user, task_text.strip())


@cl.on_message
async def on_message(msg: cl.Message):
    ctx = cl.user_session.get("team_ctx")
    if not ctx:
        return

    if ctx.get("started"):
        # Workflow already running; replies must go through the question box above.
        await cl.Message(content="The workflow is running — please answer in the question box above.").send()
        return

    task_text = (msg.content or "").strip()
    if not task_text:
        await cl.Message(content="Please type a task to start the workflow.").send()
        return

    await start_workflow(ctx["team"], ctx["user"], task_text)


def _find_latest_session_dir():
    """Return this run's conversation/<SESSION_ID>/ dir.

    The active session (set by `start_workflow`) wins. The mtime scan is only a
    fallback for when the session was never set - without that guard a stale
    fixture folder from an earlier run silently supplies the artifacts, so the
    checker reports another run's spec.
    """
    conv_root = os.path.join(PROJECT_ROOT, "conversation")
    if not os.path.isdir(conv_root):
        return None

    active = agents_tools_helpers.get_session()
    if active:
        d = os.path.join(conv_root, active)
        if os.path.isdir(d) and os.path.isfile(os.path.join(d, "functional_specification.md")):
            return d

    best_mtime, best_dir = 0.0, None
    for name in os.listdir(conv_root):
        d = os.path.join(conv_root, name)
        spec = os.path.join(d, "functional_specification.md")
        if os.path.isdir(d) and os.path.isfile(spec):
            mtime = os.path.getmtime(spec)
            if mtime > best_mtime:
                best_mtime, best_dir = mtime, d
    return best_dir


async def _present_final_artifacts():
    """After a completed run, present the full specification + diagrams in the chat."""
    from chainlit.element import File as ClFile, Image as ClImage, Pdf as ClPdf

    session_dir = _find_latest_session_dir()
    if session_dir:
        spec_path = os.path.join(session_dir, "functional_specification.md")
    else:
        # terminate_agent may not have moved the files (or failed to) - fall back to conversation/
        fallback = os.path.join(PROJECT_ROOT, "conversation", "functional_specification.md")
        if os.path.isfile(fallback):
            spec_path, session_dir = fallback, os.path.dirname(fallback)
        else:
            await cl.Message(
                content="⚠️ The workflow finished but no functional specification file was found on disk."
            ).send()
            return

    try:
        with open(spec_path, encoding="utf-8") as f:
            spec_md = f.read()
    except OSError as e:
        await cl.Message(content=f"⚠️ The workflow finished but the specification could not be read ({e}).").send()
        return

    elements = []
    artifacts = agents_tools_helpers.finalize_deliverables(session_dir)
    # Attach every diagram the canvas produced, not just the first one.
    for png in artifacts.get("diagram_pngs") or []:
        if os.path.isfile(png):
            elements.append(ClImage(path=png, name=os.path.basename(png), display="inline"))
    deliverable_pdf = os.path.join(session_dir, "functional_specification.pdf")
    if os.path.isfile(deliverable_pdf):
        elements.append(ClPdf(path=deliverable_pdf, name="functional_specification.pdf"))
    deliverable_html = os.path.join(session_dir, "functional_specification.html")
    if os.path.isfile(deliverable_html):
        elements.append(ClFile(path=deliverable_html, name="functional_specification.html"))
    if not artifacts["diagram_png"] or not artifacts["pdf"] or not artifacts["html"]:
        missing = [n for n, v in (("process_diagram.png", artifacts["diagram_png"]),
                                 ("functional_specification.pdf", artifacts["pdf"]),
                                 ("functional_specification.html", artifacts["html"])) if not v]
        await cl.Message(content=f"⚠️ Could not produce: {', '.join(missing)}").send()
    elements.append(ClFile(path=spec_path, name="functional_specification.md"))

    await cl.Message(
        content=(f"## ✅ Final deliverables\n\nFull functional specification "
                 f"(saved in `{os.path.relpath(session_dir, PROJECT_ROOT)}/`):\n\n---\n\n{spec_md}"),
        author="Final Deliverables",
        elements=elements,
    ).send()


async def start_workflow(team, user, task_text: str):
    ctx = cl.user_session.get("team_ctx")
    # Create a deterministic session folder for this run so all deliverables
    # (interview.jsonl, functional_specification.md, diagram, functional_specification.pdf)
    # land under conversation/<SESSION_ID>/ instead of the flat conversation/ dir.
    session_id = ctx.get("session_id")
    if not session_id:
        session_id = "sess-" + datetime.now(timezone.utc).strftime("%Y%m%d%H%M%S")
        ctx["session_id"] = session_id
    try:
        agents_tools_helpers.set_session(session_id)
    except Exception as e:
        print(f"⚠️  Could not set session folder ({type(e).__name__}: {e})")
    # Clear state from any previous run in this chat: without a reset the agents'
    # model contexts and the group-chat message thread accumulate across runs,
    # which makes the planner degenerate (greetings / self-assignments) on restart.
    try:
        await team.reset()
    except Exception as e:  # a failed reset must never block starting a run
        print(f"⚠️  Could not reset team state ({type(e).__name__}: {e})")
    ctx["started"] = True

    # Ground the simulated stakeholder in the task actually entered, instead of
    # a canned brief, so its answers match this run.
    human_sim = ctx.get("human_sim")
    if human_sim is not None:
        try:
            human_sim.set_brief(task_text)
        except Exception as e:
            print(f"⚠️  Could not set simulator brief ({type(e).__name__}: {e})")
    cl.user_session.set("team_ctx", ctx)

    await cl.Message(content=f"Starting multi-agent workflow for: {task_text}").send()

    current_source = None
    current_msg = None
    cancellation_token = CancellationToken()
    # No-progress guard: after a malformed tool call some models emit empty messages
    # forever (the selector keeps re-selecting the same agent until it says TERMINATE).
    # Stop with a clear error instead of looping until MaxMessageTermination.
    EMPTY_STREAK_LIMIT = 3
    empty_streak = {}

    async def _finish_stream():
        nonlocal current_msg, current_source
        if current_msg:
            await current_msg.send()
            current_msg = None
            current_source = None

    try:
        async for event in team.run_stream(task=task_text, cancellation_token=cancellation_token):
            if isinstance(event, ModelClientStreamingChunkEvent):
                if current_source != event.source or current_msg is None:
                    await _finish_stream()
                    current_source = event.source
                    current_msg = cl.Message(content="", author=current_source or "agent")
                if event.content and current_msg:
                    await current_msg.stream_token(event.content)

            elif isinstance(event, TextMessage):
                text = str(event.content).strip() if event.content is not None else ""
                src = event.source or "agent"
                if not text:
                    empty_streak[src] = empty_streak.get(src, 0) + 1
                    if empty_streak[src] >= EMPTY_STREAK_LIMIT:
                        await _finish_stream()
                        await cl.Message(
                            content=(f"⚠️ {src} produced no output {EMPTY_STREAK_LIMIT} times in a row — "
                                     "stopping to avoid an infinite loop. This usually means the model emitted empty responses (common with very large tool arguments or context overflow on local models). Type your task again to retry — each new run starts from cleared agent state; if it keeps happening, check that LM Studio is serving the expected model.")
                        ).send()
                        cancellation_token.cancel()
                        break
                else:
                    empty_streak[src] = 0
                await _finish_stream()
                if text:
                    await cl.Message(content=text, author=src).send()

            elif isinstance(event, TaskResult):
                await _finish_stream()
                await cl.Message(content=f"Workflow complete: {event.stop_reason}").send()
                try:
                    await _present_final_artifacts()
                except Exception as e:  # presentation must never break run completion
                    print(f"⚠️  Could not present final artifacts ({type(e).__name__}: {e})")
    except Exception as e:
        err = str(e)
        if "Model unloaded" in err or "400 Bad Request" in err:
            hint = ("⚠️ The local model was unloaded from LM Studio mid-run (or the request was rejected). "
                    "Reload qwen3.8-27b in LM Studio, make sure nothing else is using its VRAM, then restart this chat.")
        elif "speculative batch index" in err:
            hint = ("⚠️ LM Studio's speculative decoding crashed (llama.cpp engine bug). Restart the LM Studio "
                    "server (`lms server stop && lms server start`) and retry; disable speculative decoding for "
                    "the model if it recurs.")
        else:
            hint = f"⚠️ Workflow stopped with an error: {type(e).__name__}: {err}"
        await _finish_stream()
        await cl.Message(content=hint).send()

    if current_msg:
        await current_msg.send()

    # The run is over; allow a new task in this chat (the flag must not stay True).
    ctx["started"] = False
    cl.user_session.set("team_ctx", ctx)