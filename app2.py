# app.py (FULL MANUAL INSTANTIATION, FULL SYSTEM MESSAGES)

import os
import sys
import asyncio
import types
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

# Ensure project paths are importable when running via `chainlit run app.py`
PROJECT_ROOT = os.path.abspath(os.path.dirname(__file__))
LIB_PATH = os.path.join(PROJECT_ROOT, "lib")
SRC_PATH = os.path.join(PROJECT_ROOT, "src")
sys.path.append(LIB_PATH)
sys.path.append(SRC_PATH)

import mcp_boot 
from lib import agents_tools_helpers
from rag_helpers import rag_indexer_runner
from model_loader import load_model_client
from agents_tools_helpers import selector_func, save_conversation_to_jsonl, write_md_file_tool, read_md_file_tool, write_mermaid_to_file_tool


@cl.on_chat_start
async def on_chat_start():
    rag_vector_memory = await rag_indexer_runner(os.path.join("lib", "rag_config.yaml"))
    text_canvas_memory = TextCanvasMemory()
    update_file_tool = text_canvas_memory.get_update_file_tool()
    sys.modules["canvas"] = types.SimpleNamespace(update_file_tool=update_file_tool)

    model_client = load_model_client("openai")
    model_client_tools = load_model_client("openai_npt")

    async def chainlit_user_input(prompt=None, cancellation_token=None):
        while True:
            if cancellation_token is not None and getattr(cancellation_token, "is_canceled", False):
                raise asyncio.CancelledError()
            resp = await cl.AskUserMessage(content=" ", timeout=3600).send()
            if resp and (resp.get("content") or "").strip():
                return resp.get("content").strip()
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
    Continue until all tasks are completed, then summarize the results and end with **TERMINATE**.

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
        When mermaid_code_reviewer_agent sends **READY**, mark it as **done**, summarize findings, and end with **TERMINATE**.

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
        reflect_on_tool_use=True,
        memory=[rag_vector_memory],
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
        memory=[rag_vector_memory],
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
        memory=[rag_vector_memory],
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
        memory=[rag_vector_memory],
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
            ALWAYS call 'write_md_file_tool' exactly once.
            Pass the ENTIRE final Functional Specification as 'content'.
            Wait for a confirmation message “Markdown spec successfully written”.
            ONLY THEN send **READY**.

    **COMPLETION RULE**
        If functional_spec_checker_agent finds missing sections that require USER input:
            Wait for interviewer_agent to gather those answers, then update the Markdown and save again.
        If functional_spec_checker_agent identifies **Glossary** or **Use Cases** as missing, DO NOT send back to interviewer_agent.
            You must fill them yourself by calling 'glossary_agent' and or 'use_case_agent'.
        **DO NOT send READY until you have saved the Markdown file with 'write_md_file_tool'.**

    **IMPORTANT**
        Do NOT start until summarizer_agent has emitted **READY** (or planning_agent explicitly assigns your task).
        Always use professional, clear business language.
        Never skip any section of the template.
        Always overwrite the entire Markdown file no partial updates.
        Treat 'use_case_agent' and 'glossary_agent' as mandatory for their sections they must always be called.
        Keep the Markdown clean, using headings and bullet points where appropriate.
        Calling 'write_md_file_tool' is mandatory.
""",
        tools=[write_md_file_tool, AgentTool(agent=use_case_agent), AgentTool(agent=glossary_agent)],
        reflect_on_tool_use=True,
        memory=[rag_vector_memory],
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
        reflect_on_tool_use=True,
        memory=[rag_vector_memory],
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
        reflect_on_tool_use=True,
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
        reflect_on_tool_use=True,
        memory=[text_canvas_memory],
    )

    terminate_agent = AssistantAgent(
        name="terminate_agent",
        description="An agent that excecute the termination pipeline.",
        model_client=model_client_tools,
        system_message="""You are the TERMINATE_AGENT. Perform the final export pipeline and then end with **TERMINATE**.

    **INPUTS**
      conversation log: project_root/conversation/interview.jsonl
      spec:             project_root/conversation/functional_specification.md
      mermaid:          project_root/conversation/process_diagram.mmd

    **GOAL**
      Create: project_root/experience/<SESSION_ID>/
          interview.jsonl
          functional_specification.md
          process_diagram.mmd
          process_diagram.png  
          functional_specification.formatted.md
          deliverable.pdf

    **STEPS STRICT ORDER**
      1 Read project_root/conversation/interview.jsonl and extract the first available "session_id".
        If multiple lines: pick the first non-empty "session_id".
        If not found: set SESSION_ID = "sess-unknown".

      2 Create folder project_root/experience/<SESSION_ID>/

      3 MOVE the three source files into that folder using 'move_file':
          project_root/conversation/interview.jsonl             -> project_root/experience/<SESSION_ID>/interview.jsonl
          project_root/conversation/functional_specification.md -> project_root/experience/<SESSION_ID>/functional_specification.md
          project_root/conversation/process_diagram.mmd         -> project_root/experience/<SESSION_ID>/process_diagram.mmd

      4 Clean the Mermaid file **in place** and report issues (severity/code/message/recommendation):
          clean_mermaid(
            input_path="project_root/experience/<SESSION_ID>/process_diagram.mmd",
            output_path="project_root/experience/<SESSION_ID>/process_diagram.mmd",
            overwrite=True
          )

      5 Render Mermaid **PNG**:
          render_mermaid_png(
            input_path="project_root/experience/<SESSION_ID>/process_diagram.mmd",
            output_path="project_root/experience/<SESSION_ID>/process_diagram.png",
            theme="forest"
          )

      6 Run **format_and_export** ONLY:
          format_and_export(
            session_dir="project_root/experience/<SESSION_ID>",
            md="functional_specification.md",
            diagram="process_diagram.png",
            md_out="functional_specification.formatted.md",
            pdf_out="deliverable.pdf",
            engine="xelatex",
            toc=True, toc_depth=2, margin="1in",
            mainfont="DejaVu Serif", monofont="DejaVu Sans Mono"
          )

      7 Confirm project_root/experience/<SESSION_ID>/deliverable.pdf exists.

      8 Save experience metadata:
          save_experience_chroma(
            session_dir="project_root/experience/<SESSION_ID>",
            session_id="<SESSION_ID>"
          )

      9 Output exactly: **TERMINATE**

    **RULES**
      Be explicit about each steps success or failure.
      If a tool call fails, retry up to 1 times with the same arguments.
    """,
        tools=[*(await mcp_boot.fs_tools(PROJECT_ROOT)),
          *(await mcp_boot.mermaid_tools(PROJECT_ROOT)),
          *(await mcp_boot.pdf_format_tools(PROJECT_ROOT))],
        reflect_on_tool_use=True,
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
    termination = MaxMessageTermination(100000000) | TextMentionTermination("TERMINATE")

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
    cl.user_session.set("team_ctx", {"team": team, "user": user, "initialized": True, "started": False})

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
        # Workflow already running, treat as interview reply
        return

    task_text = (msg.content or "").strip()
    if not task_text:
        await cl.Message(content="Please type a task to start the workflow.").send()
        return

    await start_workflow(ctx["team"], ctx["user"], task_text)


async def start_workflow(team, user, task_text: str):
    ctx = cl.user_session.get("team_ctx")
    ctx["started"] = True
    cl.user_session.set("team_ctx", ctx)

    await cl.Message(content=f"Starting multi-agent workflow for: {task_text}").send()

    current_source = None
    current_msg = None

    async for event in team.run_stream(task=task_text, cancellation_token=CancellationToken()):
        if isinstance(event, ModelClientStreamingChunkEvent):
            if current_source != event.source:
                if current_msg:
                    await current_msg.send()
                current_source = event.source
                current_msg = cl.Message(content="", author=current_source or "agent")
            if event.content:
                await current_msg.stream_token(event.content)

        elif isinstance(event, TextMessage):
            if current_msg:
                await current_msg.send()
                current_msg = None
                current_source = None
            await cl.Message(content=str(event.content).strip(), author=event.source or "agent").send()

        elif isinstance(event, TaskResult):
            if current_msg:
                await current_msg.send()
                current_msg = None
                current_source = None
            await cl.Message(content=f"Workflow complete: {event.stop_reason}").send()

    if current_msg:
        await current_msg.send()