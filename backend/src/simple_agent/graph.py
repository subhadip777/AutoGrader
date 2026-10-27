import os
from dotenv import load_dotenv
from langchain_ollama import ChatOllama
from langgraph.graph import StateGraph, MessagesState, START, END

load_dotenv("D:\Autograder\.env")

llm = ChatOllama(
    model=os.getenv("OLLAMA_MODEL", "qwen2.5:0.5b"),
    base_url=os.getenv("OLLAMA_BASE_URL", "http://localhost:11434"),
    temperature=0,
    seed=42,
)

def model(state: MessagesState) -> dict:
    return {"messages": [llm.invoke(state["messages"])]}

builder = StateGraph(MessagesState)
builder.add_node("model", model)
builder.add_edge(START, "model")
builder.add_edge("model", END)
graph = builder.compile()