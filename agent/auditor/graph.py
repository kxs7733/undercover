"""The Auditor's graph, written by hand: patterns the manager dismissed before set
aside in code, a node that asks the model, LangGraph's ToolNode and the loop between
them, then a pause for the manager's decision on each finding that needs one, in a
node of its own. The checks ran in code before the graph starts, and no model call
sets a figure, a score or a decision. The graph saves its state after every step on
the audit's thread."""

import operator
from collections.abc import Callable
from functools import partial
from pathlib import Path
from typing import Annotated, Any, TypedDict, cast

from langchain.tools import ToolException
from langchain_core.language_models import BaseChatModel, LanguageModelInput
from langchain_core.messages import (
    AIMessage,
    AnyMessage,
    BaseMessage,
    HumanMessage,
    SystemMessage,
    ToolMessage,
)
from langchain_core.runnables import Runnable
from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.graph.message import add_messages
from langgraph.graph.state import CompiledStateGraph
from langgraph.prebuilt import ToolNode
from langgraph.prebuilt.tool_node import ToolCallRequest
from langgraph.runtime import Runtime
from langgraph.store.base import BaseStore
from langgraph.types import Command, interrupt

from agent.auditor import app_api, memory
from agent.auditor.tools import AUDITOR_TOOLS, AuditorContext
from agent.json_text import as_json
from agent.openrouter import usage_of
from agent.refusals import REFUSED
from agent.routes import GatewayRefused

AUDIT_MODEL_CALLS = 20
SET_ASIDE = "set_aside"
AGENT = "agent"
TOOLS = "tools"
NEXT_FINDING = "next_finding"
CONFIRM = "confirm"
RECORD_ANSWER = "record_answer"
DONE, REFUSED_STEP, FAILED = "done", "refused", "failed"
WRITE_UP = "write_up_finding"
START_AUDIT = "Please explain each of this audit's findings."
DISMISSED_BEFORE = "You dismissed this pattern before: {reason}"
# The most of a step the manager's page keeps.
STEP_TEXT = 1000
REFUSALS = (app_api.Refused, GatewayRefused, ToolException)
INSTRUCTIONS = (Path(__file__).parent / "instructions.md").read_text(encoding="utf-8")

AuditorGraph = CompiledStateGraph["AuditorState", AuditorContext, Any, Any]


class AuditorState(TypedDict):
    """What the graph keeps for an audit, saved after every step: its messages, the
    model calls and their cost, and the finding the audit waits on."""

    messages: Annotated[list[AnyMessage], add_messages]
    model_calls: Annotated[int, operator.add]
    cost: Annotated[float, operator.add]
    waiting_on: int


def findings_of(context: AuditorContext) -> list[dict[str, Any]]:
    return app_api.get_audit(context.sign_in, context.audit_id)["findings"]


def set_aside(state: AuditorState, runtime: Runtime[AuditorContext]) -> dict[str, Any]:
    """Set aside each finding this manager dismissed before, in code, before the
    model sees it, and start the model's work."""
    context = runtime.context
    store = cast(BaseStore, runtime.store)
    manager_id = context.manager["handler_id"]
    for finding in findings_of(context):
        before = memory.dismissed_before(store, manager_id, finding["fingerprint"])
        if (
            before
            and finding["status"] == app_api.OPEN
            and set(finding["claim_ids"]) <= set(before["claim_ids"])
        ):
            reason = DISMISSED_BEFORE.format(reason=before["reason"])
            app_api.set_aside(
                context.sign_in, context.audit_id, finding["finding_id"], reason
            )
            record_step(context, "search_memory", finding["fingerprint"], DONE, reason)
    return {"messages": [HumanMessage(START_AUDIT)]}


def record_step(
    context: AuditorContext, tool: str, asked: str, status: str, answer: str
) -> None:
    step: app_api.Step = {
        "tool": tool,
        "input": asked,
        "status": status,
        "answer": answer[:STEP_TEXT],
    }
    app_api.record_step(context.sign_in, context.audit_id, step)


def call_model(
    state: AuditorState,
    runtime: Runtime[AuditorContext],
    llm: Runnable[LanguageModelInput, BaseMessage],
) -> dict[str, Any]:
    """Ask the model for its next step, with the instructions for this manager, and
    keep the call's cost."""
    manager = runtime.context.manager
    system = SystemMessage(
        INSTRUCTIONS.format(name=manager["name"], role=manager["role"])
    )
    reply = llm.invoke([system, *state["messages"]])
    return {"messages": [reply], "model_calls": 1, "cost": usage_of(reply).cost}


def after_agent(state: AuditorState) -> str:
    """Run the tools the model asks for, unless it has made as many calls as an audit
    may. Either way a finding keeps at least the code's line, so the audit goes on."""
    reply = state["messages"][-1]
    if (
        isinstance(reply, AIMessage)
        and reply.tool_calls
        and state["model_calls"] < AUDIT_MODEL_CALLS
    ):
        return TOOLS
    return NEXT_FINDING


def refusal_answer(refusal: Exception) -> str:
    """A refusal as the model is told it."""
    if isinstance(refusal, app_api.Refused | GatewayRefused):
        return refusal.answer
    return REFUSED.format(reason=refusal)


def with_step(
    request: ToolCallRequest,
    execute: Callable[[ToolCallRequest], ToolMessage | Command],
) -> ToolMessage | Command:
    """Run a tool and record the step. A refusal goes back to the model; any other
    error stops the audit."""
    call = request.tool_call
    context = cast(AuditorContext, request.runtime.context)
    # What the model wrote is the finding's only when the app keeps it.
    args = call["args"]
    asked = (
        str(args.get("finding_id", "")) if call["name"] == WRITE_UP else as_json(args)
    )
    try:
        result = cast(ToolMessage, execute(request))
    except REFUSALS as refusal:
        answer = refusal_answer(refusal)
        record_step(context, call["name"], asked, REFUSED_STEP, answer)
        return ToolMessage(
            answer, tool_call_id=call["id"], name=call["name"], status="error"
        )
    record_step(context, call["name"], asked, DONE, result.text)
    return result


def next_finding(state: AuditorState, runtime: Runtime[AuditorContext]) -> Command:
    """Go to the next finding that waits for the manager's decision, or end. A
    finding about this manager is left for someone else, and doesn't wait."""
    name = runtime.context.manager["name"]
    for finding in findings_of(runtime.context):
        if (
            finding["needs_decision"]
            and finding["status"] == app_api.OPEN
            and finding["subject"] != name
        ):
            return Command(update={"waiting_on": finding["finding_id"]}, goto=CONFIRM)
    return Command(goto=END)


def confirm(state: AuditorState) -> None:
    """Pause until the manager decides the finding, which the app records. A resume
    runs this node again from the top, so nothing goes before the interrupt."""
    interrupt({"finding_id": state["waiting_on"]})


def record_answer(state: AuditorState, runtime: Runtime[AuditorContext]) -> None:
    """Remember a dismissal under this manager, so the pattern isn't raised again.
    The app already holds the decision."""
    context = runtime.context
    for finding in findings_of(context):
        if (
            finding["finding_id"] == state["waiting_on"]
            and finding["status"] == app_api.DISMISSED
        ):
            memory.remember_dismissal(
                cast(BaseStore, runtime.store),
                context.manager["handler_id"],
                finding["fingerprint"],
                finding["answer_reason"],
                finding["claim_ids"],
            )


def auditor_graph(
    llm: BaseChatModel, saver: BaseCheckpointSaver[Any], store: BaseStore
) -> AuditorGraph:
    """Build the Auditor's graph on its model, saving its state after every step with
    the saver given and each manager's dismissals in the store."""
    tools = ToolNode(AUDITOR_TOOLS, handle_tool_errors=False, wrap_tool_call=with_step)
    bound = llm.bind_tools(AUDITOR_TOOLS, parallel_tool_calls=False)
    builder = StateGraph(AuditorState, context_schema=AuditorContext)
    builder.add_node(SET_ASIDE, set_aside)
    builder.add_node(AGENT, partial(call_model, llm=bound))
    builder.add_node(TOOLS, tools)
    builder.add_node(NEXT_FINDING, next_finding, destinations=(CONFIRM, END))
    builder.add_node(CONFIRM, confirm)
    builder.add_node(RECORD_ANSWER, record_answer)
    builder.add_edge(START, SET_ASIDE)
    builder.add_edge(SET_ASIDE, AGENT)
    builder.add_conditional_edges(AGENT, after_agent, [TOOLS, NEXT_FINDING])
    builder.add_edge(TOOLS, AGENT)
    builder.add_edge(CONFIRM, RECORD_ANSWER)
    builder.add_edge(RECORD_ANSWER, NEXT_FINDING)
    return builder.compile(checkpointer=saver, store=store)
