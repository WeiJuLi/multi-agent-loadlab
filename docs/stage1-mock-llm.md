# Stage 1: Mock LLM

[← Back to README](../README.md)

A fake, OpenAI-compatible LLM server that every later load test runs against.

## Why build a fake LLM?

Load testing against a real LLM (OpenAI, Azure OpenAI) is a bad idea:

- **It costs money.** A load test sends thousands of requests, and each one triggers 3–4 LLM calls.
- **You can't reproduce it.** Real latency changes minute to minute, so two runs are never comparable.
- **You can't control failures.** To prove that retry or a circuit breaker works, you need the LLM to fail *on demand*.

So I built a mock that **looks like OpenAI from the outside**, but where I control the latency, the rate limits, and the failures.
The backend code doesn't know the difference: switching between the mock and a real LLM is just a change of `base_url`.

## What it can do

| Capability | How | Code |
|---|---|---|
| **Speaks the OpenAI API** | `POST /v1/chat/completions`, same request and response format. LangChain's `ChatOpenAI` works with no changes | [`app.py`](../mock_llm/app.py) |
| **Plays different agent roles** | Reads a `[ROLE:xxx]` tag in the system prompt and replies like that agent would | [`responses.py`](../mock_llm/responses.py) |
| **Counts tokens** | Estimates `usage` (about 4 characters per token) | [`tokens.py`](../mock_llm/tokens.py) |
| **Realistic latency** | Longer answers are slower; reading the prompt is cheap, writing the answer is expensive | [`latency.py`](../mock_llm/latency.py) |
| **Reproducible randomness** | Fixed seed: the same run gives the same latencies and the same failures | [`app.py`](../mock_llm/app.py) |
| **Rate limits like Azure** | Requests-per-minute and tokens-per-minute buckets. Returns `429` with `Retry-After` | [`rate_limiter.py`](../mock_llm/rate_limiter.py) |
| **Fails on purpose** | Random `500`s, random long hangs, or a full outage you can switch on and off | [`app.py`](../mock_llm/app.py) |
| **Configured by env vars** | Every behavior above is controlled from `.env` or the command line | [`config.py`](../mock_llm/config.py) |

---

## How a request flows through the mock

```
POST /v1/chat/completions
   │
   ⓪ Paused?  ──────────────────────────► wait here until resumed (simulates an outage)
   │
   │  estimate prompt tokens
   │
   ⓵ Rate limit (RPM + TPM buckets) ────► 429 + Retry-After
   │
   │  draw 4 random numbers, always in this order:
   │    ① response id  ② "return 500?"  ③ "hang?"  ④ latency jitter
   │
   │  build the reply for this role, estimate completion tokens
   │
   ⓶ Won the "500" draw? ───────────────► 500 server_error
   ⓷ Won the "hang" draw? ──────────────► wait an extra HANG_SECONDS
   │
   ⓸ await asyncio.sleep(latency)
   │
   └─► 200 + OpenAI-format response
```

Two design choices in this flow matter a lot:

1. **Rate limiting happens before any random number is drawn.** A request that gets a `429` doesn't use up a number from the random sequence. So whether or not some requests were throttled, everyone else still gets the same jitter.
2. **All 4 random numbers are always drawn, even when faults are turned off.** This means an experiment with `ERROR_RATE=0` and one with `ERROR_RATE=0.3` give the *same* latency to every request that didn't fail. The only difference between the two runs is which requests failed, so the comparison is fair.

---

## 1. OpenAI-compatible API

**Request** (what LangChain actually sends; I captured it):
```json
{"model": "gpt-4o-mini", "stream": false,
 "messages": [{"role": "user", "content": "hi"}],
 "max_completion_tokens": 512, "temperature": 0.0}
```

Two details I only found by capturing real traffic:
- LangChain sends **`max_completion_tokens`**, even when the code says `max_tokens`. The mock accepts both names, otherwise the TPM limit would use the wrong number.
- It also sends fields the mock doesn't use (`stream`). The request model uses `extra="allow"`, so unknown fields are accepted instead of rejected.

**Response:**
```json
{
  "id": "chatcmpl-1c80a3b1799d",
  "object": "chat.completion",
  "created": 1759550000,
  "model": "gpt-4o-mini",
  "choices": [{"index": 0, "message": {"role": "assistant", "content": "..."}, "finish_reason": "stop"}],
  "usage": {"prompt_tokens": 8, "completion_tokens": 6, "total_tokens": 14}
}
```

Errors use OpenAI's error format, so the SDK raises the right exception (`429` → `RateLimitError`, `500` → `InternalServerError`):
```json
{"error": {"message": "Rate limit exceeded. Retry after 6 seconds.", "type": "rate_limit_error", "code": "429"}}
```

---

## 2. Agent roles

The multi-agent backend (Stage 2) has four agents. Each one puts a tag at the start of its system prompt, like `[ROLE:supervisor]`.
The mock reads the tag and answers the way that agent would. A real LLM just sees the tag as normal text, so it can stay in the prompt when switching to a real model.

This table is the **contract** between the mock and the backend. Both sides have to agree on it:

| Role | What the agent sends | What the mock replies |
|---|---|---|
| `supervisor` | The user's question | JSON: `{"experts": ["knowledge", "calculator"], "reason": "..."}` |
| `knowledge` | Question + reference lines like `[FAQ-01] Q: ... A: ...` | `Based on our FAQ: ` + the first 2 answers |
| `calculator` | Question + a line `TOOL_RESULT: {...json...}` | A sentence explaining the numbers, ending with a disclaimer |
| `reviewer` | `Draft:` followed by the draft answer | `APPROVED` if the draft has the disclaimer; otherwise the draft with the disclaimer added |
| *(no tag)* | Anything | `This is a mock reply.` |

The supervisor routes with simple rules: if the question has a dollar amount **and** a term (`$20,000 ... 5 years`), it needs the calculator; if it doesn't need the calculator, or it mentions FAQ topics ("documents", "penalty", "fees"…), it needs knowledge.
It routes all **50/50** questions in the load-test question pool correctly ([`check_routing.py`](../scripts/check_routing.py)).

---

## 3. Latency model

```
latency = (base + prompt_tokens × per_prompt_token + completion_tokens × per_completion_token) × jitter
```

| Part | Why | Default |
|---|---|---|
| `base` | Network round trip and queueing at the provider. Doesn't depend on length | 200 ms |
| `per_prompt_token` | **Prefill**: the model reads the whole prompt in parallel, so each token is cheap | 0.3 ms |
| `per_completion_token` | **Decode**: the model writes one token at a time, so each token is expensive | 15 ms |
| `jitter` | Random factor between `1 − j` and `1 + j` | j = 0.2 |

Why not just "random 1–3 seconds"? With this formula, the supervisor's short JSON is fast, long answers are slow, and questions that need two experts are clearly slower. That makes later results meaningful: Little's Law predictions, the gain from running agents in parallel, and "which agent is slowest" on the dashboard.

The wait uses `await asyncio.sleep`, never `time.sleep`. I measured the difference: [Experiment 1](experiments/01-asyncio-vs-time-sleep.md).

---

## 4. Reproducible randomness

The mock uses its own `random.Random(seed)`, not Python's global `random`, so no other library can consume numbers from its sequence.

The seed fixes **the N-th random number**, not "the result of each call":

| Situation | Same ids? | Same latencies? |
|---|---|---|
| Same server, two rounds in a row (no reset) | No: the sequence keeps going | No |
| Reset before each round, requests sent **one by one** | ✅ Yes | ✅ Yes (if the content is the same) |
| Reset before each round, requests sent **at the same time** | Same set, different owners | Same set, different owners |

Under real load, requests arrive in a different order each time. So the seed keeps the mock's side of the randomness the same, and **running every experiment 3 times and taking the median** handles the rest.

`POST /admin/reset` puts the sequence back to the start (and refills the rate-limit buckets) without restarting the server.

---

## 5. Rate limiting (like Azure OpenAI)

Two **token buckets**, both must have room:

| Bucket | Size | Refills per second | Each request takes |
|---|---|---|---|
| Requests (RPM) | `RPM` | `RPM / 60` | 1 |
| Tokens (TPM) | `TPM` | `TPM / 60` | `prompt_tokens + max_tokens` |

- **Starts full**, so a burst right after startup is allowed.
- **Refills continuously**, not all at once each minute. Refill is calculated lazily from elapsed time; there's no background timer.
- **Checks both buckets before taking from either.** If the token bucket says no, the request bucket isn't charged.
- **TPM charges `max_tokens` up front**, like Azure, because the answer length isn't known yet. In practice, setting `max_tokens` too high wastes quota.
- **`Retry-After`** = how long until both buckets have enough, rounded **up** to whole seconds (`retry-after-ms` has the exact value).
- **No locks needed**: the event loop is single-threaded, and there's no `await` between checking and taking.
- **Run with one worker only.** Each worker process would get its own buckets, multiplying the real limit.

---

## 6. Fault injection

| Fault | Turn it on | What happens | What it will test (Stage 5) |
|---|---|---|---|
| Random server errors | `MOCK_LLM_ERROR_RATE=0.05` | 5% of calls return `500` | Retry |
| Random hangs | `MOCK_LLM_HANG_RATE=0.05`, `MOCK_LLM_HANG_SECONDS=20` | 5% of calls take 20 s longer | Timeout budget |
| Full outage | `POST /admin/pause?seconds=30` or `MOCK_LLM_PAUSED=true` | Every call hangs until resumed | Circuit breaker |
| Rate limiting | `MOCK_LLM_RPM`, `MOCK_LLM_TPM` | `429` + `Retry-After` | Retry with backoff and jitter |

Faulty responses carry an `x-mock-fault: error | hang` header, so they're easy to spot.

During a pause, `/health` still returns OK. That's on purpose: in real outages the process is often alive while the actual feature is stuck.

---

## Configuration

All settings come from environment variables (see [`.env.example`](../.env.example)). Command-line values override `.env`, which overrides code defaults. Defaults keep the system healthy: **every fault is off by default.**

| Variable | Default | Meaning |
|---|---|---|
| `MOCK_LLM_SEED` | 42 | Random seed |
| `MOCK_LLM_LATENCY_BASE_MS` | 200 | Fixed latency |
| `MOCK_LLM_LATENCY_PER_PROMPT_TOKEN_MS` | 0.3 | Prefill cost per prompt token |
| `MOCK_LLM_LATENCY_PER_COMPLETION_TOKEN_MS` | 15 | Decode cost per completion token |
| `MOCK_LLM_LATENCY_JITTER` | 0.2 | ±20% random noise |
| `MOCK_LLM_RATE_LIMIT_ENABLED` | true | Turn rate limiting on or off |
| `MOCK_LLM_RPM` | 1000 | Requests per minute (0 = unlimited) |
| `MOCK_LLM_TPM` | 1000000 | Tokens per minute (0 = unlimited) |
| `MOCK_LLM_DEFAULT_MAX_TOKENS` | 800 | Used for TPM when the request has no `max_tokens` |
| `MOCK_LLM_ERROR_RATE` | 0.0 | Chance of a `500` |
| `MOCK_LLM_HANG_RATE` | 0.0 | Chance of a long hang |
| `MOCK_LLM_HANG_SECONDS` | 60 | How long a hang lasts |
| `MOCK_LLM_PAUSED` | false | Start in outage mode |

## Endpoints

| Endpoint | Purpose |
|---|---|
| `POST /v1/chat/completions` | The OpenAI-compatible chat API |
| `GET /health` | "I'm alive" check |
| `GET /admin/config` | The settings actually in effect. I save this with every experiment |
| `POST /admin/reset` | Reset the random sequence and refill the rate-limit buckets |
| `POST /admin/pause?seconds=N` | Start an outage; auto-resume after N seconds (or never, if omitted) |
| `POST /admin/resume` | End the outage |

---

## How I verified it

Each check is a script I can re-run after any change (a regression test).

| Check | Script | Result |
|---|---|---|
| LangChain's `ChatOpenAI` works against the mock, and each role gives the right reply | [`verify_langchain.py`](../scripts/verify_langchain.py) | ✅ 5/5 roles |
| Supervisor routes every question in the load-test pool correctly | [`check_routing.py`](../scripts/check_routing.py) | ✅ 50/50 |
| With `RPM=10`, 30 requests at once → about 20 rejected, all with `Retry-After` | [`verify_rate_limit.py`](../scripts/verify_rate_limit.py) | ✅ 10 × `200`, 20 × `429`, `Retry-After: 6` |
| Same seed twice → same ids, latencies, and status codes | [`verify_seed.py`](../scripts/verify_seed.py) | ✅ 9/9 identical |
| Same seed twice **with faults on** (30% errors, 20% hangs) | [`verify_seed.py`](../scripts/verify_seed.py) | ✅ Same requests fail in both runs; the rest match the no-fault run exactly |
| Waiting doesn't block other requests | [Experiment 1](experiments/01-asyncio-vs-time-sleep.md) | ✅ 20 concurrent requests in 2.5 s (vs 42 s if blocking) |

The fault-run result is the important one: failures land on the same requests every time, and every request that didn't fail has exactly the same latency and id as in the no-fault run. Stage 5 relies on this to compare "with retry" against "without retry" under the exact same failures.

One thing LangChain does by default: when it gets a `429`, it **silently waits for `Retry-After` and tries again** (default 2 retries). In my test, a rate-limited call didn't raise an error; it just took 11.1 s. To keep errors visible, the backend sets `max_retries=0` until Stage 5 adds its own retry logic.

## Run it

```bash
source .venv/bin/activate
uvicorn mock_llm.app:app --port 8001 --workers 1

# Override any setting from the command line
MOCK_LLM_RPM=10 MOCK_LLM_ERROR_RATE=0.05 uvicorn mock_llm.app:app --port 8001 --workers 1

# Verification
python -m scripts.verify_langchain
python -m scripts.check_routing
python -m scripts.verify_seed
MOCK_LLM_RPM=10 uvicorn mock_llm.app:app --port 8001 --workers 1   # then:
python -m scripts.verify_rate_limit
```

## Known limitations

Being honest about what the mock *doesn't* do:

- **Routing is rule-based.** It only works because I wrote the rules for my own question pool. A real LLM routes by meaning.
- **Token counts are estimates** (about 4 characters per token), not a real tokenizer.
- **Latency doesn't grow with load.** A real provider slows down when it's busy; the mock's latency only depends on the request.
- **`500` errors return instantly.** Real errors usually happen partway through.
- **Text only.** No streaming, images, or tool calls.
- **One worker only**, because the rate-limit buckets live in memory.
- **Pause timer edge case:** `pause?seconds=30`, then `resume`, then `pause` again: the old 30-second timer can still end the second pause early.
- **Shutting down while paused** waits for stuck requests forever. Use `--timeout-graceful-shutdown 5`, or resume first.
