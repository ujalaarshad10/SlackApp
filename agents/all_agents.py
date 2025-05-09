
from langchain_google_genai import ChatGoogleGenerativeAI

from langchain.agents import create_tool_calling_agent
from langchain.agents import AgentExecutor
from langchain_openai import ChatOpenAI
from dotenv import load_dotenv
from prompt import schedule_prompt, update_prompt, delete_prompt,calender_prompt,schedule_group_prompt,update_group_prompt,schedule_channel_prompt

load_dotenv()

# Initialize the language model
llm = ChatGoogleGenerativeAI(model = "gemini-2.0-flash-exp", temperature = 0.3, max_retries=1)

def create_schedule_agent(tools):
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=schedule_prompt,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )

def create_schedule_group_agent(tools):
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=schedule_group_prompt,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )
def create_schedule_channel_agent(tools):
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=schedule_channel_prompt,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )
def create_update_group_agent(tools):
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=update_group_prompt,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )
def create_calendar_agent(tools):
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=calender_prompt,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )

def create_update_agent(tools):
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=update_prompt,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )

def create_delete_agent(tools):
    agent = create_tool_calling_agent(
        llm=llm,
        tools=tools,
        prompt=delete_prompt,
    )
    return AgentExecutor.from_agent_and_tools(
        agent=agent,
        tools=tools,
        verbose=True,
        handle_parsing_errors=True,
    )
