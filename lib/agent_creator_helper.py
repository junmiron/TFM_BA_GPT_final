"""
This module provides helper functions for creating and managing agents
that interact using memory and a RoundRobinGroupChat mechanism.

The primary function, `get_agent_response`, facilitates communication
between a user proxy agent and an assistant agent to retrieve responses
to user queries.
"""

from autogen_agentchat.agents import AssistantAgent, UserProxyAgent

# New function to ask a question and get a response


async def create_agent_interviewer(model_client, vector_memory, input_func=None):
    """
    Creates a user proxy agent and an assistant agent, then returns both.

    This function sets up a user proxy agent and an assistant agent with
    memory and a system message. The returned agents can then be used for
    further processing such as integrating them into a communication channel.

    Args:
        model_client: The model client used by the assistant agent.
        vector_memory: The memory object used by the assistant agent.
        input_func: Optional callable for user input (used by the user proxy agent).

    Returns:
        tuple: A tuple of user_proxy, assistant_agent representing the
        created agents.
    """
    user_proxy = UserProxyAgent(
            name="user",
            description="A human user",
            input_func=input,
        )

    planning_agent = AssistantAgent(
        name="planning_agent",
        description="An agent for planning tasks, this agent should be the first to engage when given a new task.",
        model_client=model_client,
        memory=[vector_memory],
        system_message="""
        You are a planning agent.
        Your job is to break down complex tasks into smaller, manageable subtasks.
        Your team members are:
            Interviewer: ask the user questions to gather information
            summarizer: summarize all the information provided and ask the user for feedback
            user: the human user who will provide information and feedback

        You only plan and delegate tasks - you do not execute them yourself.

        When assigning tasks, use this format:
        1. <agent> : <task>

        After assigning tasks, wait for all agents to finish their tasks.
        After all tasks are complete, summarize the findings and end with "TERMINATE".
        """,
    )

    interviewer_agent = AssistantAgent(
            name="interviewer",
            description="An agent to ask questions to a human.",
            model_client=model_client,
            memory=[vector_memory],
            system_message=(
                "You are a Business Analyst."
                "You will ask the user questions one by one to gather information about"
                "the scope and requirements for a project."
                "You will use the RAG memory to get help and context to ask questions"
            ),
            model_client_stream=True,  # Enable model client streaming.
        )

    summarizer_agent = AssistantAgent(
            name="summarizer",
            description="An agent that summarizes the information provided.",
            model_client=model_client,
            system_message=(
                "You are an expert on making summaries."
                "Summarize the the information provided by the interviewer then"
                "handoff the summary to the user and ask the user if he wants to add more information,"
                "if the user says yes, you will handoff the conversation to the interviewer"
                "and let him know the user have more information."
            ),
            model_client_stream=True,  # Enable model client streaming.
        )

    return user_proxy, interviewer_agent, summarizer_agent, planning_agent
