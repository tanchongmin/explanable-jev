# Jev-style Typed Evaluator

This is a small local implementation inspired by TypeSafe Jev. It lets a user submit one `state` and several typed questions, then returns constrained answers:

- `choice`: `choice`
- `score`: `score`, `legend`
- `true/false`: `noul`

It uses OpenAI `gpt-5-mini` by default, but the model is isolated behind `llm.py` so you can use any LLM provider.

## Run

```bash
python3 server.py
```

Open:

```text
http://127.0.0.1:8000
```

The app reads `OPENAI_API_KEY` from `.env`. You can optionally set:

```env
OPENAI_MODEL=gpt-5-mini
OPENAI_REASONING_EFFORT=minimal
PORT=8000
```

`OPENAI_REASONING_EFFORT` is passed to OpenAI's Responses API as `reasoning.effort`. For `gpt-5-mini`, `minimal` is the fast low-thinking setting. If you switch to a model that supports `none`, set `OPENAI_REASONING_EFFORT=none`.

## Swapping the LLM

Edit `llm.py` and keep this function signature:

```python
def llm(system_prompt: str, user_prompt: str) -> str:
    return "..."
```

The returned string can be any text. `server.py` handles interpretation, post-processing, and retry/repair if the first answer cannot be parsed into the required typed shape. For example, to route through a local model, replace the body of `llm` with your local client call and return the model's raw text.

The initial LLM prompt is intentionally short:

- Choice asks for one option token like `a`, `b`, or `c`
- Score asks for one score token like `0`, `1`, or `2`
- True/False asks for `t` or `f`
- Explanation mode adds one short reason; turning it off removes that request

The LLM is not asked for probability distributions, and the API does not return probability or confidence fields.

The LLM is also not asked to return JSON. The server first tries to interpret a plain answer like `billing`, `1.5`, or `0.82`. If interpretation fails, it retries with another plain-answer prompt instead of requesting JSON.

Evaluation prompts are compact plain text, not JSON. For example:

```text
State:
ticket: refund duplicate

Q: Which team?
Answer this MCQ with exactly one option token. Options: a) billing: payments; b) returns: exchanges. Return token only.
```

## UI Workflow

The browser UI keeps `state` as a key-value table. Add fields like:

- `ticket_message`: customer text
- `refund_policy`: policy text
- `account_tier`: plan name

Each row becomes one key under the `state` object sent to the server.

For questions, enter the question you want answered and the option keys or score levels. Use **Auto describe** to ask the configured LLM to fill in short descriptions for the options. The descriptions remain editable before evaluation.

## Request Shape

The browser sends:

```json
{
  "state": {
    "ticket_message": "I was charged twice. Please refund the duplicate."
  },
  "explanationMode": true,
  "questions": {
    "refund_requested": {
      "type": "noul",
      "instructions": "Does `ticket_message` request a refund?"
    },
    "department": {
      "type": "choice",
      "instructions": "Which team should handle `ticket_message`?",
      "criteria": {
        "billing": "Payments, invoicing, refunds",
        "technical": "Bugs, outages, integrations",
        "sales": "Pricing, upgrades, new accounts"
      }
    },
    "frustration": {
      "type": "score",
      "instructions": "How frustrated is the customer?",
      "criteria": ["Calm", "Frustrated", "Very angry"]
    }
  }
}
```

With explanation mode enabled, every answer also includes:

```json
{
  "explanation": "Short reason for the judgment."
}
```

## Description Generation

The UI calls `/api/describe` with a question type, question text, option keys, and current state. The endpoint asks the LLM for plain-text lines:

```text
billing: Payments, duplicate charges, invoices, and refunds.
returns: Exchanges, wrong sizes, damaged items, and returns.
```

The server parses those lines and writes them back into the criteria fields.

## Speed and Parallelism

Each question is evaluated independently in a `ThreadPoolExecutor`. `parallelism` in the API response is the number of question workers used for that request. Each question is exactly one LLM call; parallelism only lets several different questions run at the same time.

The server then normalizes outputs in code:

- raw LLM text is interpreted into the requested typed output shape
- failed interpretation is retried with a short plain-answer prompt
- answers are clamped to the declared type and allowed range

This keeps downstream code working with predictable typed shapes even if the underlying LLM is imperfect.
