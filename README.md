# Multi-Agent Chatbot Backend: Load Testing & Distributed Systems Lab

A personal practice project. I'm building the backend for a **multi-agent customer-service chatbot**, then load testing it step by step: sync vs async, fault tolerance, horizontal scaling, task queues, caching, monitoring, and the cloud.

Every number in this repo comes from a recorded experiment, so you can trace each claim back to how it was measured.

## The idea

A user asks a loan question. A **Supervisor** agent decides which experts are needed, the experts answer, and a **Reviewer** checks the result before it goes back to the user.

```
                      ┌─► Knowledge  (searches a fake FAQ) ──┐
User ─► Supervisor ───┤                                      ├─► Reviewer ─► Answer
                      └─► Calculator (monthly payment tool) ─┘
```

One user question turns into **3–4 LLM calls**. That's what makes this a good playground for load testing: LLM calls are slow, rate-limited, and sometimes fail.

All data is made up (a fictional "Starlight Bank"), and the load tests run against a **mock LLM** instead of a real one. That keeps the tests free, repeatable, and lets me inject failures on purpose.

## Roadmap

| Stage | What |
|---|---|
| 0 | Environment, project structure, fake data |
| 1 | [Mock LLM](docs/stage1-mock-llm.md): OpenAI-compatible, rate-limited, fault injection |
| 2 | Multi-agent backend (sync version, LangGraph + FastAPI) |
| 3 | Baseline load test (Locust) |
| 4 | Async rewrite + parallel agents |
| 5 | Fault tolerance: timeouts, retry, circuit breaker, fallback |
| 6 | Docker + horizontal scaling behind Nginx |
| 7 | Task queue + idempotency (Redis) |
| 8 | Caching |
| 9 | Monitoring (Prometheus + Grafana) |
| 10 | Cloud deployment + cloud load test (Azure) |

## Stage 1: Mock LLM

An OpenAI-compatible fake LLM with realistic latency, Azure-style rate limits, and on-demand failures, so load tests are free and repeatable. [Details →](docs/stage1-mock-llm.md)

### Experiment: `asyncio.sleep` vs `time.sleep`

The mock fakes model latency by sleeping. I sent 1–20 requests at once and timed each batch, changing only that one sleep line.

![asyncio.sleep vs time.sleep](experiments/charts/asyncio_vs_time_sleep.png)

**Findings**

1. **Non-blocking wait scales.** With `await asyncio.sleep`, 20 requests took 2.5 s, about the same as 1. The event loop serves others while one waits.
2. **One blocking line serializes everything.** With `time.sleep`, 20 requests took 42.2 s (**17× slower**), almost exactly 20 × 2.1 s.
3. **A batch waits for its slowest request.** More requests means more chances to hit the slow end of the jitter, the same reason p99 gets worse with more users.
4. **The server's own timer hides queueing.** Server-reported latency was ~2 s in *both* versions; the 40 s spent waiting in line was invisible to it. Measure from the client side.

[Full setup, raw data, and analysis →](docs/experiments/01-asyncio-vs-time-sleep.md) · Every run is logged in [`experiments/log.csv`](experiments/log.csv)

## How I run experiments

1. **Change one thing at a time.**
2. **Predict first, then measure** (using Little's Law).
3. **Warm up, then run each step for at least 5 minutes.**
4. **Run each setup 3 times and take the median**, with a fixed random seed.
5. **Log every run**, including the prediction and what I learned.

A note on the numbers: they all come from the mock LLM, not a real model. That's on purpose: it keeps costs at zero and makes results repeatable. Real-world latency would look different.

## Quick start

```bash
python3.12 -m venv .venv && source .venv/bin/activate
pip install fastapi "uvicorn[standard]" httpx requests langgraph langchain-openai locust pandas matplotlib python-dotenv
cp .env.example .env

# Start the mock LLM
uvicorn mock_llm.app:app --port 8001 --workers 1

# In another terminal: check it works
python -m scripts.verify_langchain
```

## Project layout

```
mock_llm/      Mock OpenAI-compatible LLM (Stage 1)
backend/       Multi-agent backend (Stage 2+)
data/          Fake FAQ, rate table, load-test question pool
scripts/       Verification and experiment scripts
experiments/   Experiment log, raw results, charts
docs/          Detailed write-ups for each stage and experiment
loadtest/      Locust scripts (Stage 3+)
infra/         Docker, Nginx, Prometheus, Grafana (Stage 6+)
```
