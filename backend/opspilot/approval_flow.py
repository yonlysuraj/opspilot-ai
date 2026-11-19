from typing import TypedDict

from langgraph.checkpoint.sqlite.aio import AsyncSqliteSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt

from .config import Settings
from .models import Approval, RunResult
from .storage import ApprovalConflict, Store


class ApprovalState(TypedDict, total=False):
    proposal_id: str
    task_id: str
    previous_status: str
    new_status: str
    answer: str


def proposal_fields(proposal: Approval) -> ApprovalState:
    return {
        "proposal_id": str(proposal.id),
        "task_id": proposal.task_id,
        "previous_status": proposal.previous_status,
        "new_status": proposal.new_status,
    }


def workflow(checkpointer: AsyncSqliteSaver):
    def await_decision(state: ApprovalState) -> dict:
        decision = interrupt(state)
        task = state["task_id"]
        if decision == "approved":
            return {"answer": f"Approval recorded. {task} changed from {state['previous_status']} to {state['new_status']}."}
        if decision == "rejected":
            return {"answer": f"The proposed status update for {task} was rejected. The run made no task change."}
        raise ValueError("Invalid approval decision.")

    graph = StateGraph(ApprovalState)
    graph.add_node("await_decision", await_decision)
    graph.add_edge(START, "await_decision")
    graph.add_edge("await_decision", END)
    return graph.compile(checkpointer=checkpointer)


async def pause_approval(settings: Settings, proposal: Approval) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoints_path)) as checkpointer:
        graph = workflow(checkpointer)
        result = await graph.ainvoke(
            proposal_fields(proposal), {"configurable": {"thread_id": str(proposal.run_id)}}
        )
        if not result.get("__interrupt__"):
            raise RuntimeError("The approval checkpoint did not pause.")


async def check_approval(settings: Settings, proposal: Approval) -> None:
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoints_path)) as checkpointer:
        snapshot = await workflow(checkpointer).aget_state({"configurable": {"thread_id": str(proposal.run_id)}})
        matches = all(snapshot.values.get(key) == value for key, value in proposal_fields(proposal).items())
        if not matches or (proposal.status == "pending" and not snapshot.interrupts):
            raise ApprovalConflict("The workflow checkpoint does not match this proposal.")


async def resume_approval(settings: Settings, store: Store, proposal: Approval) -> None:
    run = store.get_run(proposal.requester_id, str(proposal.run_id))
    if run is None or run["status"] != "awaiting_approval":
        return
    async with AsyncSqliteSaver.from_conn_string(str(settings.checkpoints_path)) as checkpointer:
        graph = workflow(checkpointer)
        config = {"configurable": {"thread_id": str(proposal.run_id)}}
        snapshot = await graph.aget_state(config)
        answer = snapshot.values.get("answer")
        if not answer:
            outcome = await graph.ainvoke(Command(resume=proposal.status), config)
            answer = outcome.get("answer")
    if not answer:
        raise RuntimeError("The approval decision could not resume the workflow.")
    result = RunResult.model_validate(run["result"]).model_copy(update={"answer": answer})
    store.finish_run(str(proposal.run_id), result, None)
