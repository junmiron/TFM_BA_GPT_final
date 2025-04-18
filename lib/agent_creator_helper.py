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
        name="user_proxy",
        description="A human user",
        input_func=input_func,
    )

    interviewer_agent = AssistantAgent(
        name="interviewer",
        model_client=model_client,
        handoffs=["summarizer", "user"],
        memory=[vector_memory],
        system_message=(
            "You are a professional interviewer."
            "You will ask the user questions to gather information about:"
            "the scope and requirements for a change request, a new feature"
            "or a project."
            "You will use the RAG memory to get help and context for questions"
            "When the user say FINISH, you will end the interview and handoff the conversation"""
            "to the summarizer."
        ),
        model_client_stream=True,  # Enable model client streaming.
    )

    summarizer_agent = AssistantAgent(
        name="summarizer",
        model_client=model_client,
        handoffs=["interviewer", "user"],
        memory=[vector_memory],
        system_message=(
            "You are an expert on making summaries."
            "You will summarize the conversation between the user and the interviewer."
            "You will present the summary to the user."
            "You will also ask the user if they want to add more information."
            "If the user says yes, you will handoff the conversation to the interviewer."
        ),
        model_client_stream=True,  # Enable model client streaming.
    )

    return user_proxy, interviewer_agent, summarizer_agent
