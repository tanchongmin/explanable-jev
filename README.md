# Explanable Jev

A small local evaluator inspired by TypeSafe Jev. It lets you define shared `state`, ask several typed questions against that state, and returns constrained answers: `choice`, `score`, or `true/false`.

This repo serves two functions:

1. LLM-based easy generation of state and question input fields for Jev.
2. Using local or closed-source LLMs to emulate Jev and get an explanation in addition to traditional Jev outputs.

![Overview of the Jev-style typed evaluator UI](Overview.png)

Inspiration: [Introducing System One Models and Jev](https://typesafe.ai/blog/introducing-system-one-models-and-jev).

The default LLM adapter uses OpenAI `gpt-5-mini`, but model access is isolated behind `llm.py` so you can swap in another provider.

## Run

```bash
python3 server.py
```

Open:

```text
http://127.0.0.1:8000
```

The app reads `OPENAI_API_KEY` from `.env` or the environment. Optional settings:

```env
OPENAI_MODEL=gpt-5-mini
OPENAI_REASONING_EFFORT=minimal
PORT=8000
```

`OPENAI_REASONING_EFFORT` is passed to OpenAI's Responses API as `reasoning.effort`.

## UI Workflow

The browser UI has two main panes:

- **State**: key-value fields that every question can reference, such as `ticket_message`, `refund_policy`, `movie_review`, or `review_metadata`.
- **Questions**: typed judgments against that state. The supported question types are Choice, Score, and True/False.
- **Answers**: normalized typed outputs, optional explanations, and collapsed State, Questions, and Output JSON blocks with copy controls.

Use **Generate** to describe the evaluator you want in a sentence or two. The app asks the configured LLM to generate a new setup from scratch with specific editable state values and 3 to 5 typed questions.

![Generate workflow for creating state and questions](generate.png)

Use **Refine** to change the current setup with a short instruction. The app sends the current state and questions to the LLM, applies the requested refinement, validates the result, and reloads it into the editable UI. After a successful refinement, **Revert** restores the previous setup if you do not like the change.

![Refine workflow with revert support](refine.png)

Use **Auto describe** on an individual question to fill in concise option or rubric descriptions.

Generated and refined setups follow two extra rules:

- Generated state keys may use any name except `input_text` and `input`.
- Every generated/refined question instruction must explicitly refer to at least one state key, preferably with backticks, such as `` `ticket_message` ``. Backticked variables in questions must be keys from `state`.

## Request Shape

The browser builds Jev-style requests from the editable state table and question cards. `/api/evaluate` receives `state` and `questions`, with an optional local `explanationMode` extension for adding explanations to the Jev-style output:

```json
{
  "state": {
    "ticket_message": "I was charged twice. Please refund the duplicate.",
    "refund_policy": "Duplicate charges are eligible for refund after verification."
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
        "billing": "Payments, invoices, refunds, or duplicate charges.",
        "technical": "Bugs, outages, errors, or integrations.",
        "returns": "Exchanges, damaged items, or wrong items."
      }
    },
    "frustration": {
      "type": "score",
      "instructions": "How frustrated is the customer in `ticket_message`?",
      "criteria": ["Calm", "Frustrated", "Very angry"]
    }
  }
}
```

## Output Shape

Each question is evaluated independently and normalized into a predictable typed answer:

- `choice`: returns one declared option key.
- `score`: returns a number clamped to the declared score range, plus a legend.
- `noul`: returns `1` for true or `0` for false.

The Answers pane includes three collapsed, copyable JSON blocks. Click a block to expand or collapse it, or use the clipboard icon in the top-right of the block to copy its JSON:

- **State JSON**: the Jev-compatible `state` object assembled from the current editor. It is available before evaluation and updates as you edit.
- **Questions JSON**: the Jev-compatible `questions` object assembled from the current editor. True/False questions are exported as Jev `noul` questions.
- **Output JSON**: Jev-style output with `model` and `answers`. Explanations are added as an extra key on each answer.

State JSON looks like:

```json
{
  "ticket_message": "I was charged twice. Please refund the duplicate.",
  "refund_policy": "Duplicate charges are eligible for refund after verification."
}
```

Questions JSON looks like:

```json
{
  "refund_requested": {
    "type": "noul",
    "instructions": "Does `ticket_message` request a refund?"
  },
  "department": {
    "type": "choice",
    "instructions": "Which team should handle `ticket_message`?",
    "criteria": {
      "billing": "Payments, invoices, refunds, or duplicate charges.",
      "technical": "Bugs, outages, errors, or integrations.",
      "returns": "Exchanges, damaged items, or wrong items."
    }
  }
}
```

With explanation mode enabled, Output JSON looks like:

```json
{
  "model": "gpt-5-mini",
  "answers": {
    "refund_requested": {
      "type": "noul",
      "noul": 1,
      "explanation": "The customer explicitly asks to refund the duplicate charge."
    },
    "department": {
      "type": "choice",
      "choice": "billing",
      "confidence": 1,
      "probabilities": {
        "billing": 1,
        "technical": 0,
        "returns": 0
      },
      "explanation": "The ticket is about duplicate payment and refund handling."
    },
    "frustration": {
      "type": "score",
      "score": 1,
      "confidence": 1,
      "probabilities": {
        "1": 1
      },
      "legend": {
        "0": "Calm",
        "1": "Frustrated",
        "2": "Very angry"
      },
      "explanation": "The customer is concerned but not abusive."
    }
  },
  "usage": {
    "input_tokens": 0,
    "cost_usd": 0,
    "credits_remaining_usd": 0
  }
}
```

## Generation Endpoints

`/api/generate` powers the **Generate** button:

```json
{
  "description": "Classify support tickets by urgency, team, and refund eligibility."
}
```

`/api/refine` powers the **Refine** button:

```json
{
  "instruction": "Add a compliance question and make urgency a 5-point score.",
  "current": {
    "state": {},
    "questions": {}
  }
}
```

Both endpoints ask the LLM for JSON containing `state` and `questions`, then validate the result before returning it to the browser.

If generated JSON is invalid or fails validation, the server sends the failed output and exact validation error back to the LLM for repair, up to 3 total attempts.

## Description Generation

`/api/describe` fills in option descriptions for one existing question. It receives a question type, question text, option keys, and current state, then asks the LLM for plain-text lines:

```text
billing: Payments, duplicate charges, invoices, and refunds.
returns: Exchanges, wrong sizes, damaged items, and returns.
```

The server parses those lines and writes them back into the criteria fields.

## Evaluation Behavior

Evaluation prompts are intentionally compact plain text, not JSON. For example:

```text
State:
ticket_message: refund duplicate

Q: Which team should handle `ticket_message`?
Answer this MCQ with exactly one option token. Options: a) billing: payments; b) returns: exchanges. Return token only.
```

The LLM is not asked for probabilities or confidence scores. The server:

- interprets plain answers like `a`, `1`, or `t`
- retries with a short repair prompt if the answer cannot be parsed
- clamps answers to the declared type and allowed range
- runs separate questions in parallel

## Swapping The LLM

Edit `llm.py` and keep this function signature:

```python
def llm(system_prompt: str, user_prompt: str) -> str:
    return "..."
```

The rest of the app only expects a string response. `server.py` handles interpretation, validation, post-processing, and retries.
