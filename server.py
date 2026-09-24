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
    q_type = question["type"]
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
    q_type = question["type"]
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
            result = {"noul": True}
        elif normalized == "f" or re.search(r"\bno\b|\bfalse\b", answer_text, re.I):
            result = {"noul": False}
        elif re.match(r"^\s*t\b", text, re.I):
            result = {"noul": True}
        elif re.match(r"^\s*f\b", text, re.I):
            result = {"noul": False}
        elif re.search(r"\byes\b|\btrue\b", text, re.I):
            result = {"noul": True}
        elif re.search(r"\bno\b|\bfalse\b", text, re.I):
            result = {"noul": False}
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


def validate_question(question_id: str, question: Any) -> dict[str, Any]:
    if not re.fullmatch(r"[A-Za-z][A-Za-z0-9_-]{0,63}", question_id):
        raise ValidationError(
            f"Question id '{question_id}' must start with a letter and use letters, numbers, _ or -."
        )
    if not isinstance(question, dict):
        raise ValidationError(f"Question '{question_id}' must be an object.")
    if not isinstance(question.get("instructions"), (str, dict, list)):
        raise ValidationError(f"Question '{question_id}' needs instructions.")

    q_type = question.get("type")
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
    elif q_type == "noul":
        criteria = question.get("criteria")
        if criteria is not None:
            if not isinstance(criteria, dict):
                raise ValidationError(f"True/False '{question_id}' criteria must be an object.")
            for key in criteria:
                if key not in {"true", "false"}:
                    raise ValidationError(f"True/False '{question_id}' criteria only supports true/false.")
    else:
        raise ValidationError(f"Question '{question_id}' type must be choice, score, or noul.")

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
    q_type = question["type"]

    if q_type == "choice":
        options = list(question["criteria"].keys())
        token_map = choice_tokens(options)
        raw_choice = str(raw.get("choice", "")).strip()
        choice = token_map.get(raw_choice.lower(), raw_choice)
        choice = choice if choice in options else options[0]
        answer: dict[str, Any] = {
            "type": "choice",
            "choice": choice,
        }
    elif q_type == "score":
        try:
            score = float(raw.get("score", 0.0))
        except (TypeError, ValueError):
            score = 0.0
        score = max(0.0, min(float(len(question["criteria"]) - 1), score))
        answer = {
            "type": "score",
            "score": round(score, 4),
            "legend": {str(index): value for index, value in enumerate(question["criteria"])},
        }
    else:
        value = raw.get("noul", False)
        if isinstance(value, bool):
            noul = value
        elif isinstance(value, (int, float)):
            noul = value >= 0.5
        else:
            noul = str(value).strip().lower() in {"true", "yes", "1"}
        answer = {"type": "noul", "noul": noul}

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
    answer["prompt"] = {
        "system": system_prompt,
        "user": user_prompt,
    }
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
        "parallelism": max_workers,
        "elapsed_ms": round((time.perf_counter() - started) * 1000),
        "answers": {question_id: answers[question_id] for question_id in validated},
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
    q_type = payload.get("type")
    instructions = payload.get("instructions")
    options = payload.get("options")

    if q_type not in {"choice", "score", "noul"}:
        raise ValidationError("type must be choice, score, or noul.")
    if not isinstance(instructions, str) or not instructions.strip():
        raise ValidationError("instructions is required.")

    if q_type == "noul":
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
        if path not in {"/api/evaluate", "/api/describe"}:
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        try:
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
            if not isinstance(payload, dict):
                raise ValidationError("Request body must be an object.")
            result = evaluate_payload(payload) if path == "/api/evaluate" else describe_payload(payload)
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
