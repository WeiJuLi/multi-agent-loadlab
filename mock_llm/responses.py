import json
import re

ROLE_PATTERN = re.compile(r"\[ROLE:(\w+)\]")
DISCLAIMER = (
    "Note: This information is for reference only. "
    "Final rates and terms are subject to Starlight Bank's review."
)


# ---------- 工具函式 ----------

def extract_role(messages: list[dict]) -> str | None:
    # 從 system 訊息找出 [ROLE:xxx]，找不到回 None
    for message in messages:
        if message["role"] == "system":
            match = ROLE_PATTERN.search(message["content"])
            if match:
                return match.group(1)
    return None


def last_user_message(messages: list[dict]) -> str:
    # 回傳「最後一則」user 訊息的內容；沒有就回空字串
    for message in reversed(messages):
        if message["role"] == "user":
            return message["content"]
    return ""


# ---------- Supervisor ----------

# "$20,000"、"$ 5,000"
AMOUNT_PATTERN = re.compile(r"\$\s?[\d,]+")
# "5 years"、"48 months"、"1 year"
TERM_PATTERN = re.compile(r"\b\d+\s*(?:years?|months?)\b", re.IGNORECASE)
# 出現這些詞，代表問題裡有「需要查 FAQ」的部分
KNOWLEDGE_PHRASES = (
    "document", "need to provide", "penalty", "fixed or variable", "used car",
    "approval", "fee", "repayment start", "qualif", "bad credit",
    "receive the money", "appraisal", "apply online", "discount", "miss a payment",
)


def _supervisor_reply(question: str) -> str:
    q = question.lower()
    # 同時有「金額」和「期限」才需要試算
    needs_calculator = bool(AMOUNT_PATTERN.search(q) and TERM_PATTERN.search(q))
    # 不需要試算 → 一定要查 FAQ（不然沒人回答）；需要試算 → 有 FAQ 關鍵詞才查
    needs_knowledge = not needs_calculator or any(phrase in q for phrase in KNOWLEDGE_PHRASES)

    experts = []
    if needs_knowledge:
        experts.append("knowledge")
    if needs_calculator:
        experts.append("calculator")
    return json.dumps({"experts": experts, "reason": f"Routed to {', '.join(experts)}."})


# ---------- Knowledge ----------

# 抓出每一行 "[FAQ-01] Q: ... A: <這裡>"
FAQ_ANSWER_PATTERN = re.compile(r"^\[FAQ-\d+\] Q: .*? A: (.+)$", re.MULTILINE)


def _knowledge_reply(user_content: str) -> str:
    # 取前 2 筆 FAQ 的答案組成回答
    answers = FAQ_ANSWER_PATTERN.findall(user_content)
    if not answers:
        return "I couldn't find relevant information in our FAQ."
    return "Based on our FAQ: " + " ".join(answers[:2])


# ---------- Calculator ----------

TOOL_RESULT_PATTERN = re.compile(r"TOOL_RESULT: (\{.*\})")


def _calculator_reply(user_content: str) -> str:
    match = TOOL_RESULT_PATTERN.search(user_content)
    if not match:
        return "I need the loan amount and term to calculate the monthly payment."
    result = json.loads(match.group(1))

    principal = result["principal"]
    annual_rate_pct = result["annual_rate_pct"]
    months = result["months"]
    monthly_payment = result["monthly_payment"]
    total_interest = result["total_interest"]
    total_paid = result["total_paid"]

    return (
        f"For a loan of ${principal:,.2f} at {annual_rate_pct}% annual interest "
        f"over {months} months, the estimated monthly payment is ${monthly_payment:,.2f}. "
        f"Total interest is about ${total_interest:,.2f}, "
        f"so you would repay ${total_paid:,.2f} in total. {DISCLAIMER}"
    )


# ---------- Reviewer ----------

def _reviewer_reply(user_content: str) -> str:
    # 草稿已附提醒 → 通過；沒有 → 回傳補上提醒的修正版
    _, _, draft = user_content.partition("Draft:")
    draft = draft.strip()
    if DISCLAIMER in draft:
        return "APPROVED"
    return f"{draft}\n\n{DISCLAIMER}"


# ---------- 入口 ----------

def generate_reply(messages: list[dict]) -> str:
    role = extract_role(messages)
    user_content = last_user_message(messages)
    handlers = {
        "supervisor": _supervisor_reply,
        "knowledge": _knowledge_reply,
        "calculator": _calculator_reply,
        "reviewer": _reviewer_reply,
    }
    handler = handlers.get(role)
    if handler is None:
        return "This is a mock reply."
    return handler(user_content)
