from __future__ import annotations

import json
import os
import re
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from llm import llm


ROOT = Path(__file__).parent
WEB_ROOT = ROOT / "web"
MAX_WORKERS = max(2, min(16, (os.cpu_count() or 4) * 2))
MAX_INTERPRET_ATTEMPTS = 3
MAX_GENERATION_ATTEMPTS = 3


class ValidationError(ValueError):
    pass


def parse_json_object(raw: str) -> dict[str, Any]:
    try:
        value = json.loads(raw)
    except json.JSONDecodeError:
        match = re.search(r"\{.*\}", raw, flags=re.DOTALL)
        if not match:
            raise
        value = json.loads(match.group(0))
    if not isinstance(value, dict):
        raise ValidationError("Model output must be a JSON object.")
    return value


def choice_tokens(options: list[str]) -> dict[str, str]:
    alphabet = "abcdefghijklmnopqrstuvwxyz"
    return {
        alphabet[index] if index < len(alphabet) else str(index): option
        for index, option in enumerate(options)
    }


def answer_contract(question: dict[str, Any], explanation_mode: bool) -> str:
    q_type = canonical_question_type(question["type"])
    explanation = " Format: token - reason." if explanation_mode else " Return token only."

    if q_type == "choice":
        token_map = choice_tokens(list(question["criteria"].keys()))
        options = "; ".join(
            f"{token}) {option}: {question['criteria'][option]}"
            for token, option in token_map.items()
        )
        return f"Answer this MCQ with exactly one option token. Options: {options}." + explanation
    if q_type == "score":
        top = len(question["criteria"]) - 1
        levels = "; ".join(f"{index}) {level}" for index, level in enumerate(question["criteria"]))
        return f"Answer this MCQ with exactly one score token. Options: {levels}." + explanation
    criteria = question.get("criteria") or {}
    true_definition = criteria.get("true", "the statement is true")
    false_definition = criteria.get("false", "the statement is false")
    return (
        "Answer this MCQ with exactly one token. "
        f"Options: t) true: {true_definition}; f) false: {false_definition}."
        + explanation
    )


def compact_state(state: Any) -> str:
    if isinstance(state, dict):
        return "\n".join(f"{key}: {value}" for key, value in state.items())
    if isinstance(state, list):
        return "\n".join(f"- {value}" for value in state)
    return str(state)


def interpret_plain_text(
    raw_output: str, question: dict[str, Any], explanation_mode: bool
) -> dict[str, Any] | None:
    text = raw_output.strip()
    if not text:
        return None

    explanation = ""
    first_line = text.splitlines()[0].strip()
    if " - " in first_line:
        answer_text, explanation = first_line.split(" - ", 1)
    elif ": " in first_line:
        answer_text, explanation = first_line.split(": ", 1)
    else:
        answer_text = first_line

    result: dict[str, Any]
    q_type = canonical_question_type(question["type"])
    if q_type == "choice":
        options = list(question["criteria"].keys())
        token_map = choice_tokens(options)
        normalized = answer_text.strip().strip("\"`.,").lower()
        selected = token_map.get(normalized)
        if selected is None:
            first_token = re.split(r"\s+", normalized)[0] if normalized else ""
            selected = token_map.get(first_token)
        if selected is None:
            match = re.search(r"\b([a-z]|\d+)\b", text, re.I)
            if match:
                selected = token_map.get(match.group(1).lower())
        if selected is None:
            reverse_tokens = {option.lower(): option for option in options}
            selected = reverse_tokens.get(normalized)
        if selected is None:
            selected = next((option for option in options if option.lower() == normalized), None)
        if selected is None:
            selected = next((option for option in options if re.search(rf"\b{re.escape(option)}\b", text, re.I)), None)
        if selected is None:
            return None
        result = {"choice": selected}
    elif q_type == "score":
        match = re.search(r"-?\d+(?:\.\d+)?", answer_text)
        if match is None:
            match = re.search(r"-?\d+(?:\.\d+)?", text)
        if match is None:
            return None
        result = {"score": float(match.group(0))}
    else:
        normalized = answer_text.strip().strip("\"`.,").lower()
        if normalized == "t" or re.search(r"\byes\b|\btrue\b", answer_text, re.I):
            result = {"true/false": True}
        elif normalized == "f" or re.search(r"\bno\b|\bfalse\b", answer_text, re.I):
            result = {"true/false": False}
        elif re.match(r"^\s*t\b", text, re.I):
            result = {"true/false": True}
        elif re.match(r"^\s*f\b", text, re.I):
            result = {"true/false": False}
        elif re.search(r"\byes\b|\btrue\b", text, re.I):
            result = {"true/false": True}
        elif re.search(r"\bno\b|\bfalse\b", text, re.I):
            result = {"true/false": False}
        else:
            return None

    if explanation_mode:
        result["explanation"] = explanation.strip()
    return result


def interpret_llm_output(
    raw_output: str,
    state: Any,
    question_id: str,
    question: dict[str, Any],
    explanation_mode: bool,
) -> dict[str, Any]:
    interpreted = interpret_plain_text(raw_output, question, explanation_mode)
    if interpreted is not None:
        return interpreted

    try:
        return parse_json_object(raw_output)
    except Exception as first_error:
        last_error: Exception = first_error

    for attempt in range(2, MAX_INTERPRET_ATTEMPTS + 1):
        repair_system = (
            "Rewrite as the required short answer. No JSON."
        )
        repair_user = (
            f"Need: {answer_contract(question, explanation_mode)}\n"
            f"Question: {question.get('instructions', '')}\n"
            f"Bad answer: {raw_output}"
        )
        repaired = llm(repair_system, repair_user)
        interpreted = interpret_plain_text(repaired, question, explanation_mode)
        if interpreted is not None:
            return interpreted
        try:
            return parse_json_object(repaired)
        except Exception as exc:
            last_error = exc
        raw_output = repaired

    raise ValidationError(f"Could not interpret LLM output for '{question_id}': {last_error}")


def validate_text_json(value: Any, path: str = "state") -> None:
    if isinstance(value, str):
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_text_json(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            if not isinstance(key, str):
                raise ValidationError(f"{path} keys must be strings.")
            validate_text_json(item, f"{path}.{key}")
        return
    raise ValidationError(f"{path} must contain only strings, objects, and arrays.")


def canonical_question_type(q_type: Any) -> Any:
    return "true/false" if q_type in {"bool", "noul"} else q_type


def validate_question(question_id: str, question: Any) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", question_id):
        raise ValidationError(
            f"Question id '{question_id}' must start with a letter and use letters, numbers, _ or -."
        )
    if not isinstance(question, dict):
        raise ValidationError(f"Question '{question_id}' must be an object.")
    if not isinstance(question.get("instructions"), (str, dict, list)):
        raise ValidationError(f"Question '{question_id}' needs instructions.")

    q_type = canonical_question_type(question.get("type"))
    if q_type != question.get("type"):
        question = dict(question)
        question["type"] = q_type
    if q_type == "choice":
        criteria = question.get("criteria")
        if not isinstance(criteria, dict) or len(criteria) < 2:
            raise ValidationError(f"Choice '{question_id}' needs at least two options.")
        if len(criteria) > 255:
            raise ValidationError(f"Choice '{question_id}' can have at most 255 options.")
        for option, description in criteria.items():
            if not isinstance(option, str) or not option:
                raise ValidationError(f"Choice '{question_id}' has an invalid option key.")
            if description is not None and not isinstance(description, (str, dict, list)):
                raise ValidationError(f"Choice '{question_id}' option '{option}' has invalid criteria.")
    elif q_type == "score":
        criteria = question.get("criteria")
        if not isinstance(criteria, list) or not (2 <= len(criteria) <= 10):
            raise ValidationError(f"Score '{question_id}' needs 2 to 10 levels.")
        for index, level in enumerate(criteria):
            if not isinstance(level, (str, dict, list)):
                raise ValidationError(f"Score '{question_id}' level {index} has invalid criteria.")
    elif q_type == "true/false":
        criteria = question.get("criteria")
        if criteria is not None:
            if not isinstance(criteria, dict):
                raise ValidationError(f"True/False '{question_id}' criteria must be an object.")
            for key in criteria:
                if key not in {"true", "false"}:
                    raise ValidationError(f"True/False '{question_id}' criteria only supports true/false.")
    else:
        raise ValidationError(f"Question '{question_id}' type must be choice, score, or true/false.")

    return question


def prompt_for_question(
    state: Any, question_id: str, question: dict[str, Any], explanation_mode: bool
) -> tuple[str, str]:
    system_prompt = "Answer the MCQ briefly."
    user_prompt = (
        f"State:\n{compact_state(state)}\n\n"
        f"Q: {question['instructions']}\n"
        f"{answer_contract(question, explanation_mode)}"
    )
    return system_prompt, user_prompt


def build_answer(question: dict[str, Any], raw: dict[str, Any], explanation_mode: bool) -> dict[str, Any]:
    q_type = canonical_question_type(question["type"])

    if q_type == "choice":
        options = list(question["criteria"].keys())
        token_map = choice_tokens(options)
        raw_choice = str(raw.get("choice", "")).strip()
        choice = token_map.get(raw_choice.lower(), raw_choice)
        choice = choice if choice in options else options[0]
        probabilities = {option: 1 if option == choice else 0 for option in options}
        answer: dict[str, Any] = {
            "type": "choice",
            "choice": choice,
            "confidence": 1,
            "probabilities": probabilities,
        }
    elif q_type == "score":
        try:
            score = float(raw.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(float(len(question["criteria"]) - 1), score))
        probability_key = str(round(score))
        answer = {
            "type": "score",
            "score": round(score, 4),
            "confidence": 1,
            "probabilities": {probability_key: 1},
            "legend": {str(index): value for index, value in enumerate(question["criteria"])},
        }
    else:
        value = raw.get("true/false", raw.get("bool", raw.get("noul", False)))
        if isinstance(value, bool):
            bool_value = value
        elif isinstance(value, (int, float)):
            bool_value = value >= 0.5
        else:
            bool_value = str(value).strip().lower() in {"true", "yes", "1"}
        answer = {"type": "noul", "noul": 1 if bool_value else 0}

    if explanation_mode:
        explanation = raw.get("explanation")
        answer["explanation"] = explanation if isinstance(explanation, str) else ""

    return answer


def evaluate_question(
    state: Any, question_id: str, question: dict[str, Any], explanation_mode: bool
) -> tuple[str, dict[str, Any]]:
    system_prompt, user_prompt = prompt_for_question(state, question_id, question, explanation_mode)
    raw_output = llm(system_prompt, user_prompt)
    raw = interpret_llm_output(raw_output, state, question_id, question, explanation_mode)
    answer = build_answer(question, raw, explanation_mode)
    return question_id, answer


def evaluate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    state = payload.get("state")
    questions = payload.get("questions")
    explanation_mode = bool(payload.get("explanationMode", False))

    validate_text_json(state)
    if not isinstance(questions, dict) or not questions:
        raise ValidationError("questions must be a non-empty object.")

    validated = {
        question_id: validate_question(question_id, question)
        for question_id, question in questions.items()
    }

    started = time.perf_counter()
    answers: dict[str, Any] = {}
    max_workers = min(MAX_WORKERS, len(validated))
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        futures = [
            executor.submit(evaluate_question, state, question_id, question, explanation_mode)
            for question_id, question in validated.items()
        ]
        for future in as_completed(futures):
            question_id, answer = future.result()
            answers[question_id] = answer

    return {
        "model": os.environ.get("OPENAI_MODEL", "gpt-5-mini"),
        "answers": {question_id: answers[question_id] for question_id in validated},
        "usage": {
            "input_tokens": 0,
            "cost_usd": 0,
            "credits_remaining_usd": 0,
        },
    }


def parse_description_lines(raw: str, keys: list[str]) -> dict[str, str]:
    descriptions: dict[str, str] = {}
    remaining = set(keys)
    for line in raw.splitlines():
        cleaned = line.strip().lstrip("-*").strip()
        if not cleaned:
            continue
        key = ""
        value = ""
        for separator in (":", "-", "="):
            if separator in cleaned:
                key, value = cleaned.split(separator, 1)
                break
        if not key:
            continue
        normalized = key.strip().strip('"`').lower()
        match = next((candidate for candidate in keys if candidate.lower() == normalized), None)
        if match is not None and value.strip():
            descriptions[match] = value.strip()
            remaining.discard(match)

    for key in remaining:
        descriptions[key] = key.replace("_", " ").strip()
    return descriptions


def describe_payload(payload: dict[str, Any]) -> dict[str, Any]:
    q_type = canonical_question_type(payload.get("type"))
    instructions = payload.get("instructions")
    options = payload.get("options")

    if q_type not in {"choice", "score", "true/false"}:
        raise ValidationError("type must be choice, score, or true/false.")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValidationError("instructions is required.")

    if q_type == "true/false":
        keys = ["true", "false"]
    else:
        if not isinstance(options, list):
            raise ValidationError("options must be a list.")
        keys = [str(option).strip() for option in options if str(option).strip()]
        if q_type == "choice" and len(keys) < 2:
            raise ValidationError("choice needs at least two options.")
        if q_type == "score" and not (2 <= len(keys) <= 10):
            raise ValidationError("score needs 2 to 10 levels.")

    state = payload.get("state", {})
    system_prompt = (
        "Generate short option descriptions for a typed judgment UI. "
        "Return plain text only. One line per key. Format: key: description."
    )
    user_prompt = json.dumps(
        {
            "question_type": q_type,
            "question": instructions,
            "keys": keys,
            "state": state,
            "requirements": "Each description should clarify when that key is the right answer. Keep each under 14 words.",
        },
        ensure_ascii=False,
    )
    raw_output = llm(system_prompt, user_prompt)
    return {"descriptions": parse_description_lines(raw_output, keys)}


def normalize_assist_questions(raw_questions: Any) -> dict[str, Any]:
    if isinstance(raw_questions, list):
        questions = {}
        for index, question in enumerate(raw_questions, start=1):
            if not isinstance(question, dict):
                raise ValidationError("Generated questions must be objects.")
            question = dict(question)
            question_id = str(question.pop("id", "")).strip() or f"question_{index}"
            questions[question_id] = question
        return questions
    if isinstance(raw_questions, dict):
        return raw_questions
    raise ValidationError("Generated questions must be an object or list.")


def normalize_generated_score_criteria(question: dict[str, Any]) -> dict[str, Any]:
    if canonical_question_type(question.get("type")) != "score":
        return question

    normalized = dict(question)
    normalized["type"] = "score"
    criteria = normalized.get("criteria")
    if isinstance(criteria, dict):
        levels = [value for value in criteria.values() if value not in (None, "")]
    elif isinstance(criteria, list):
        levels = [value for value in criteria if value not in (None, "")]
    elif isinstance(criteria, str) and criteria.strip():
        levels = [criteria.strip()]
    else:
        levels = []

    if len(levels) == 1:
        level = str(levels[0]).strip()
        levels = [
            f"Low or no evidence of: {level}",
            level,
        ]
    elif not levels:
        instructions = normalized.get("instructions", "the requested judgment")
        levels = [
            f"Low or no evidence for {instructions}.",
            f"Clear evidence for {instructions}.",
        ]

    normalized["criteria"] = levels[:10]
    return normalized


def normalize_generated_questions(raw_questions: Any) -> dict[str, Any]:
    normalized = {}
    for question_id, question in normalize_assist_questions(raw_questions).items():
        if isinstance(question, dict) and question.get("type") in {"bool", "noul"}:
            question = {**question, "type": "true/false"}
        normalized[question_id] = normalize_generated_score_criteria(question)
    return normalized


def validate_generated_state_keys(state: Any) -> dict[str, Any]:
    if not isinstance(state, dict) or not state:
        raise ValidationError("Generated state must be a non-empty object.")

    disallowed_keys = {"input", "input_text"}
    for key in state:
        normalized = key.strip().lower()
        if normalized in disallowed_keys:
            raise ValidationError(
                f"Generated state key '{key}' is not allowed. Use a more specific state key."
            )
    validate_text_json(state)
    validate_generated_state_values(state)
    return state


def validate_generated_state_values(value: Any, path: str = "state") -> None:
    placeholder_patterns = [
        r"\bpaste\b.*\bhere\b",
        r"\benter\b.*\bhere\b",
        r"\badd\b.*\bhere\b",
        r"\bfill\b.*\bhere\b",
        r"\bplaceholder\b",
        r"\bsample text\b",
        r"\blorem ipsum\b",
        r"^\s*(tbd|n/a|todo|example)\s*$",
    ]
    if isinstance(value, str):
        if not value.strip():
            raise ValidationError(f"Generated {path} must not be empty.")
        normalized = value.strip().lower()
        if any(re.search(pattern, normalized) for pattern in placeholder_patterns):
            raise ValidationError(
                f"Generated {path} must be a specific sample value, not a placeholder."
            )
        return
    if isinstance(value, list):
        for index, item in enumerate(value):
            validate_generated_state_values(item, f"{path}[{index}]")
        return
    if isinstance(value, dict):
        for key, item in value.items():
            validate_generated_state_values(item, f"{path}.{key}")


def instruction_mentions_state_key(instructions: Any, state_keys: list[str]) -> bool:
    instruction_text = json.dumps(instructions, ensure_ascii=False) if not isinstance(instructions, str) else instructions
    return any(
        re.search(rf"(?<![A-Za-z0-9_-])`?{re.escape(key)}`?(?![A-Za-z0-9_-])", instruction_text)
        for key in state_keys
    )


def backticked_variables(instructions: Any) -> set[str]:
    instruction_text = json.dumps(instructions, ensure_ascii=False) if not isinstance(instructions, str) else instructions
    return set(re.findall(r"`([A-Za-z][A-Za-z0-9_-]*)`", instruction_text))


def validate_generated_questions(questions: Any, state: dict[str, Any]) -> dict[str, Any]:
    state_keys = list(state.keys())
    state_key_set = set(state_keys)
    validated = {
        question_id: validate_question(question_id, question)
        for question_id, question in normalize_generated_questions(questions).items()
    }
    if not validated:
        raise ValidationError("Generated setup needs at least one question.")
    for question_id, question in validated.items():
        unknown_variables = sorted(backticked_variables(question.get("instructions", "")) - state_key_set)
        if unknown_variables:
            raise ValidationError(
                f"Generated question '{question_id}' refers to unknown variable(s): {', '.join(unknown_variables)}. "
                f"Use only state keys: {', '.join(state_keys)}."
            )
        if not instruction_mentions_state_key(question.get("instructions", ""), state_keys):
            raise ValidationError(
                f"Generated question '{question_id}' must refer to at least one state key: {', '.join(state_keys)}."
            )
    return validated


def validate_generated_setup(generated: dict[str, Any]) -> dict[str, Any]:
    state = validate_generated_state_keys(generated.get("state"))
    questions = validate_generated_questions(generated.get("questions"), state)
    return {"state": state, "questions": questions}


def generation_repair_prompt(original_user_prompt: str, raw_output: str, error: Exception) -> str:
    return json.dumps(
        {
            "task": "Repair the previous typed evaluator setup. Return corrected JSON only.",
            "validation_error": str(error),
            "failed_output": raw_output,
            "original_request": json.loads(original_user_prompt),
            "requirements": [
                "Return one JSON object with state and questions.",
                "state keys must not be input_text or input.",
                "state values must be specific sample content, not placeholders like 'paste here', 'enter here', or 'TBD'.",
                "Each question instruction must explicitly refer to at least one returned state key.",
                "Question instructions must not refer to variables outside the returned state keys.",
                "choice criteria must be an object with at least 2 options.",
                "score criteria must be a JSON array with 2 to 10 ordered string levels; never return a single score level.",
                "true/false criteria may contain true and false descriptions.",
            ],
        },
        ensure_ascii=False,
    )


def generate_valid_setup(system_prompt: str, user_prompt: str) -> dict[str, Any]:
    current_user_prompt = user_prompt
    last_error: Exception | None = None
    raw_output = ""

    for attempt in range(1, MAX_GENERATION_ATTEMPTS + 1):
        raw_output = llm(system_prompt, current_user_prompt)
        try:
            generated = parse_json_object(raw_output)
            return validate_generated_setup(generated)
        except Exception as exc:
            last_error = exc
            if attempt == MAX_GENERATION_ATTEMPTS:
                break
            current_user_prompt = generation_repair_prompt(user_prompt, raw_output, exc)

    raise ValidationError(
        f"Could not generate a valid setup after {MAX_GENERATION_ATTEMPTS} attempts: {last_error}"
    )


def generate_payload(payload: dict[str, Any]) -> dict[str, Any]:
    description = payload.get("description")
    if not isinstance(description, str) or not description.strip():
        raise ValidationError("description is required.")
    if len(description) > 2000:
        raise ValidationError("description must be 2000 characters or fewer.")

    system_prompt = (
        "Design a typed evaluator setup for a small UI. Return JSON only. "
        "Generate a brand-new setup from the user's description; do not reuse any existing state or questions. "
        "The JSON object must contain state and questions. "
        "state must be an object of editable string fields with specific, realistic sample values. "
        "Do not use placeholder state values such as 'Paste here', 'Enter text here', 'TBD', or generic filler. "
        "Use state keys such as ticket_message, refund_policy, loan_application, or patient_note. "
        "Do not use input_text or input as state keys. "
        "questions must be an object keyed by concise snake_case ids. "
        "Every question instruction must explicitly refer to at least one state key, preferably in backticks. "
        "If an instruction uses a backticked variable, it must exactly match a key in state; do not invent variables outside state. "
        "Each question must use type choice, score, or true/false. "
        "Choice criteria must be an object with 2 to 6 option keys and short descriptions. "
        "Score criteria must be a JSON array with 2 to 6 ordered level descriptions; never create a score question with only one level. "
        "Bool criteria may define true and false descriptions. "
        "Create 3 to 5 useful questions."
    )
    user_prompt = json.dumps(
        {
            "description": description.strip(),
            "output_contract": "Return only JSON with top-level state and questions.",
        },
        ensure_ascii=False,
    )

    return generate_valid_setup(system_prompt, user_prompt)


def refine_payload(payload: dict[str, Any]) -> dict[str, Any]:
    instruction = payload.get("instruction")
    current = payload.get("current")
    if not isinstance(instruction, str) or not instruction.strip():
        raise ValidationError("instruction is required.")
    if len(instruction) > 2000:
        raise ValidationError("instruction must be 2000 characters or fewer.")
    if not isinstance(current, dict):
        raise ValidationError("current setup is required.")

    state = current.get("state", {})
    questions = current.get("questions", {})
    if not isinstance(state, dict):
        raise ValidationError("current.state must be an object.")
    if not isinstance(questions, dict):
        raise ValidationError("current.questions must be an object.")
    validate_text_json(state)

    system_prompt = (
        "Refine a typed evaluator setup for a small UI. Return JSON only. "
        "Preserve useful existing fields and questions unless the user asks to change them. "
        "The JSON object must contain state and questions. "
        "state must be an object of editable string fields. "
        "Use state keys such as ticket_message, refund_policy, loan_application, or patient_note; replace input_text or input. "
        "questions must be an object keyed by concise snake_case ids. "
        "Every question instruction must explicitly refer to at least one returned state key, preferably in backticks. "
        "If an instruction uses a backticked variable, it must exactly match a returned state key; do not invent variables outside state. "
        "Each question must use type choice, score, or true/false. "
        "Choice criteria must be an object with 2 to 8 option keys and short descriptions. "
        "Score criteria must be a JSON array with 2 to 8 ordered level descriptions; never create a score question with only one level. "
        "True/false criteria may define true and false descriptions. "
        "Make the refined setup coherent and ready to evaluate."
    )
    user_prompt = json.dumps(
        {
            "instruction": instruction.strip(),
            "current_setup": {
                "state": state,
                "questions": questions,
            },
        },
        ensure_ascii=False,
    )

    return generate_valid_setup(system_prompt, user_prompt)


class Handler(SimpleHTTPRequestHandler):
    def __init__(self, *args: Any, **kwargs: Any) -> None:
        super().__init__(*args, directory=str(WEB_ROOT), **kwargs)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path not in {"/api/evaluate", "/api/describe", "/api/generate", "/api/assist", "/api/refine"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValidationError("Request body must be an object.")
            if path == "/api/evaluate":
                result = evaluate_payload(payload)
            elif path == "/api/describe":
                result = describe_payload(payload)
            elif path in {"/api/generate", "/api/assist"}:
                result = generate_payload(payload)
            else:
                result = refine_payload(payload)
            self.respond_json(result)
        except ValidationError as exc:
            self.respond_json({"error": str(exc)}, HTTPStatus.UNPROCESSABLE_ENTITY)
        except Exception as exc:
            self.respond_json({"error": str(exc)}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def respond_json(self, payload: dict[str, Any], status: HTTPStatus = HTTPStatus.OK) -> None:
        body = json.dumps(payload, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)


def main() -> None:
    port = int(os.environ.get("PORT", "8000"))
    server = ThreadingHTTPServer(("127.0.0.1", port), Handler)
    print(f"Jev-style evaluator running at http://127.0.0.1:{port}")
    server.serve_forever()


if __name__ == "__main__":
    main()
