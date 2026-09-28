from typing import Optional
from typing_extensions import TypedDict, Annotated
from langgraph.graph import StateGraph, START, END
from langgraph.graph.message import add_messages
from langchain_groq import ChatGroq
from langchain_core.messages import HumanMessage, AIMessage, BaseMessage
from langsmith import traceable

from app.config import get_settings

class AgentState(TypedDict):
    messages: Annotated[list[BaseMessage], add_messages]
    error: Optional[str]
    retry_count: int
    model_used: str

class ProductionAgent:

    def __init__(self):
        settings = get_settings()

        self.primary_llm = ChatGroq(
            model= settings.primary_model,
            temperature=0,
            timeout=30,
            max_retries=0,
            api_key=settings.groq_api_key,
        )

        self.fallback_llm = ChatGroq(
            model=settings.fallback_model,
            temperature=0,
            timeout=30,
            max_retries=0,
            api_key=settings.groq_api_key,
        )
        self.max_retries = settings.max_retries
        self.graph = self._build_graph()

    def _build_graph(self):

        def process_message(state: AgentState) -> dict:
            try:
                response = self.primary_llm.invoke(state["messages"])
                return{
                    "messages":[response],
                    "error": None,
                    "model_used" : "primary", 
                }
            except Exception as e:
                return{
                    "error": str(e),
                    "retry_count": state["retry_count"] +1,
                    "model_used": "",
                }

        def try_fallback(state: AgentState) -> dict:
            try:
                response = self.fallback_llm.invoke(state["messages"])
                return{
                    "messages": [response],
                    "error": None,
                    "model_used": "fallback",
                }
            except Exception as e:
                return{
                    "error": str(e),
                    "model_used": "",
                }
        def handle_error(state: AgentState) -> dict:
                return{
                    "messages": [
                        AIMessage(content=(
                            "I'm sorry, I'm having trouble processing your request "
                            "right now. Please try again in a moment."
                        ))
                    ],
                    "model_used": "error_handler",
                }

        def route_after_process(state: AgentState) -> str:
            if state.get("error") is None:
                return"done"
            elif state["retry_count"]< self.max_retries:
                return"fallback"
            else:
                return"error"

        def route_after_fallback(state: AgentState) -> str:
             if state.get("error") is None:
                  return "done"
             else:
                  return "error"

        graph = StateGraph(AgentState)

        graph.add_node("process", process_message)
        graph.add_node("fallback", try_fallback)
        graph.add_node("error", handle_error)
        graph.add_edge(START, "process")
        graph.add_conditional_edges(
             "process",
             route_after_process,
             {"done": END, "fallback": "fallback", "error": "error"},
        )
        graph.add_conditional_edges(
             "fallback",
             route_after_fallback,
             {"done": END, "error": "error"},
        )
        graph.add_edge("error", END)
        return graph.compile()

    @traceable(name="production_agent_invoke")
    def invoke(self, message:str) -> dict:

             result = self.graph.invoke({
                  "messages": [HumanMessage(content=message)],
                  "error": None,
                  "retry_count": 0,
                  "model_used": "",
             })

             return{
                  "response": result["messages"][-1].content,
                  "model_used": result.get("model_used","unknown"),
                  "error": result.get("error"),
             }


                      
                


