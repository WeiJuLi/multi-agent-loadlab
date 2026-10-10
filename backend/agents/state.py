from typing import Annotated, TypedDict

from langchain_core.messages import AnyMessage
from langgraph.graph.message import add_messages


class StepRecord(TypedDict):
    """每個節點執行一次留下的紀錄，之後找瓶頸、算成本都靠它。"""

    node: str
    seconds: float
    llm_calls: int
    input_tokens: int
    output_tokens: int


def merge_steps(left: list[StepRecord] | None, right: list[StepRecord] | None) -> list[StepRecord]:
    # 收到 None = 新一輪對話開始，清空；否則把新紀錄接在後面
    # 不能用 operator.add：有對話記憶時，上一輪的紀錄會一直累積下去
    if right is None:
        return []
    return (left or []) + right


def merge_results(left: dict[str, str] | None, right: dict[str, str] | None) -> dict[str, str]:
    # 規則和 merge_steps 一樣，合併的是 dict
    # 階段 4 讓 knowledge 和 calculator 同時跑時，兩邊的結果都要保留，不能互相覆蓋
    if right is None:
        return {}
    return {**(left or {}), **right}


class AgentState(TypedDict, total=False):
    # 對話紀錄：跨輪保留（第 5 課的記憶），只放給 LLM 看的內容
    messages: Annotated[list[AnyMessage], add_messages]

    # 以下每輪重設（API 每輪傳入新的 question，並傳 None 清空兩個累加欄位）
    question: str
    # supervisor 的路由決定，例如 ["knowledge", "calculator"]
    route: list[str]
    # 各專家的結果，例如 {"knowledge": "...", "calculator": "..."}
    expert_results: Annotated[dict[str, str], merge_results]
    # reviewer 審查後的最終回答
    final_answer: str
    # 每個節點的耗時與 token 用量
    steps: Annotated[list[StepRecord], merge_steps]
