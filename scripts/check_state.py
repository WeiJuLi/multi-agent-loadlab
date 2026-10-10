"""確認 state 的 reducer 行為正確：平常累加、收到 None 就清空，而且跨輪不會累積。

Usage:
    python -m scripts.check_state
"""

from langchain_core.messages import AIMessage, HumanMessage
from langgraph.checkpoint.memory import InMemorySaver
from langgraph.graph import END, START, StateGraph

from backend.agents.state import AgentState, merge_results, merge_steps

step_a = {"node": "a", "seconds": 0.1, "llm_calls": 1, "input_tokens": 10, "output_tokens": 5}
step_b = {"node": "b", "seconds": 0.2, "llm_calls": 0, "input_tokens": 0, "output_tokens": 0}

# ---------- 1. reducer 本身 ----------
assert merge_steps([step_a], [step_b]) == [step_a, step_b], "應該累加"
assert merge_steps([step_a], None) == [], "None 應該清空"
assert merge_steps(None, [step_a]) == [step_a], "一開始沒有值也要能用"

assert merge_results({"knowledge": "K"}, {"calculator": "C"}) == {"knowledge": "K", "calculator": "C"}
assert merge_results({"knowledge": "K"}, None) == {}
assert merge_results(None, {"calculator": "C"}) == {"calculator": "C"}
print("✅ reducer checks passed")


# ---------- 2. 放進真的 LangGraph + 對話記憶，跑兩輪 ----------
def node_a(state: AgentState) -> dict:
    return {"steps": [step_a], "expert_results": {"knowledge": "K"}}


def node_b(state: AgentState) -> dict:
    return {"steps": [step_b], "expert_results": {"calculator": "C"},
            "messages": [AIMessage("answer")]}


graph = StateGraph(AgentState)
graph.add_node("a", node_a)
graph.add_node("b", node_b)
graph.add_edge(START, "a")
graph.add_edge("a", "b")
graph.add_edge("b", END)
app = graph.compile(checkpointer=InMemorySaver())

config = {"configurable": {"thread_id": "check-state"}}
for turn in (1, 2):
    out = app.invoke(
        # 每輪：新的問題 + 用 None 清空累加欄位
        {"messages": [HumanMessage(f"question {turn}")], "question": f"question {turn}",
         "steps": None, "expert_results": None},
        config,
    )
    nodes = [s["node"] for s in out["steps"]]
    assert nodes == ["a", "b"], f"第 {turn} 輪 steps 應該只有這一輪的紀錄，實際是 {nodes}"
    assert out["expert_results"] == {"knowledge": "K", "calculator": "C"}
    # messages 要跨輪保留：每輪 +2（問題 + 回答）
    assert len(out["messages"]) == 2 * turn, f"第 {turn} 輪應該有 {2 * turn} 則訊息"
    print(f"✅ turn {turn}: steps={nodes}, expert_results={out['expert_results']}, "
          f"messages={len(out['messages'])}")

print("\n✅ all state checks passed")
