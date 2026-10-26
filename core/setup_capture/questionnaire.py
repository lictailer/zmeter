"""Questionnaire generation: prompt, model call, fallback suggestions.

The model sees the scan settings (or a whole queue), one instrument snapshot,
the experiment description, the previous answers and the lab-context files,
and returns up to ``MAX_QUESTIONS`` questions in a fixed JSON schema.  When
no API key is set or the call fails, the questions listed in
``suggested_questions.md`` are shown instead, so the tab always works.
"""

from __future__ import annotations

import copy
import datetime as _dt
import json
import os
import re
import threading
import time
from typing import Callable, Iterable, Mapping

from PyQt6 import QtCore

from . import profile

MAX_QUESTIONS = 30
QUESTION_KINDS = ("text", "number", "yes_no", "choice", "pin")
STATUS_ANSWERED = "answered"
STATUS_UNKNOWN = "unknown"
STATUS_NOT_ANSWERED = "not_answered"
STATUS_PREFILLED = "prefilled"
PROMPT_VERSION = "5"
# Thinking models (deepseek-v4-pro, Claude with effort) count their reasoning
# against this limit; billing is only for tokens actually produced.
MAX_OUTPUT_TOKENS = 32000
# Write each model run (prompt, raw reply, parsed result) to a .md file in the
# data folder for review.  Set False to stop.
SAVE_MODEL_OUTPUT = True
DEBUG_KEY = "_debug"
SECTIONS = ("scan", "setup")

CONFIDENCE_LEVELS = ("high", "medium")
INFERENCE_MODEL = "model"
INFERENCE_CORRECTED = "user_corrected"
INFERENCE_REJECTED = "rejected"
INFERENCE_CONFIRMED = "user_confirmed"
# Starter fields so scan files stay comparable; the model may add others.
# "role:<device id>" and "axis:<channel>" are per-device / per-axis fields.
INFERENCE_FIELDS = (
    ("measurement_type", "Measurement type"),
    ("role:<device id>", "Role of each device"),
    ("axis:<swept channel>", "Physical meaning of each swept axis"),
    ("polarization_config", "Polarization configuration"),
    ("temperature", "Temperature"),
    ("magnetic_field", "Magnetic field"),
    ("sample", "Sample"),
)

# Only id/text/section (and field/value/confidence) are required: every
# output token costs time, so empty keys are left out.
QUESTION_SCHEMA = {
    "type": "object",
    "properties": {
        "inferences": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "field": {"type": "string"},
                    "value": {"type": "string"},
                    "confidence": {"type": "string", "enum": list(CONFIDENCE_LEVELS)},
                    "basis": {"type": "string"},
                    "scope": {"type": "string"},
                },
                "required": ["field", "value", "confidence"],
                "additionalProperties": False,
            },
        },
        "questions": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "id": {"type": "string"},
                    "text": {"type": "string"},
                    "section": {"type": "string", "enum": list(SECTIONS)},
                    "options": {"type": "array", "items": {"type": "string"}},
                    "unit": {"type": "string"},
                },
                "required": ["id", "text", "section"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["inferences", "questions"],
    "additionalProperties": False,
}

SYSTEM_PREAMBLE = """You fill in a short setup record for ZMeter, a measurement program used \
by several physics labs. The lab context below is background and suggestions, not strict \
rules; use your judgement. Return only the JSON object the schema asks for, compact, \
leaving out optional keys that would be empty.

The record reads like a document: one line per fact, one short answer per line.

"inferences": facts you can conclude from the scan name, comments, settings, snapshot and \
description without asking. The scan name is a strong clue (e.g. "SHG" = second harmonic \
generation, "NLH" = nonlinear Hall, "3p4K" = 3.4 K, "xy" = crossed polarization).
- field: snake_case. Use these when they apply: {inference_fields}. Add others if useful.
- value: a few words. Do not repeat numbers already in the scan settings (ranges, points).
- confidence: "high" when the clue is explicit, "medium" for a reasonable guess. The user \
checks medium ones in the same list, so never ask a question about any inference. Skip \
anything weaker and ask it instead.
- basis: the clue, 2-4 words; only for medium ones.
- scope: only in a queue: "queue" for facts shared by all scans, or the exact scan name.
- previous_corrections lists conclusions a user fixed or rejected before: respect them.

"questions": the facts you still need. suggested_questions.md is a menu, not a \
checklist: pick what fits this measurement type and the clues in the scan. When the \
result can depend on history (gate sweeps, correlated or hysteretic states), ask how the \
state was prepared.
- text: a short field label, not a sentence and no question mark, e.g. "Current \
temperature", "Laser power at sample", "Goal of this scan".
- section: "scan" for what can differ from scan to scan (sample spot, power, temperature, \
goal, what changed since the last scan); "setup" for what rarely changes (wiring, lasers, \
optics). Most questions should be about this scan; keep setup ones few.
- id: short snake_case; reuse the id of a previous answer for the same field.
- options: 2-5 short likely answers whenever you can guess them, so most lines take one \
click. They are examples, never the only allowed answers; the user can type anything.
- unit: only for a number.
ZMeter fills in previous answers itself. At most {max_questions} questions, most useful \
first. Never put a range or limit in a question; any answer is allowed."""


def now_text() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


# ---------------------------------------------------------------- payload --

def _setter_summary(setter: Mapping) -> dict:
    summary = {"channel": setter.get("channel")}
    linear = setter.get("linear_setting")
    explicit = setter.get("explicit")
    destinations = setter.get("destinations")
    if explicit and isinstance(setter.get("explicit_setting"), list):
        values = setter.get("explicit_setting")
        summary["explicit_values"] = values[:20]
        summary["points"] = len(values)
    elif isinstance(linear, Mapping):
        for key in ("start", "end", "step", "points"):
            if key in linear:
                summary[key] = linear[key]
    if isinstance(destinations, list) and "points" not in summary:
        summary["points"] = len(destinations)
    return summary


def summarize_scan(info: Mapping) -> dict:
    """Compact, model-readable view of one scan definition."""

    levels_out = {}
    levels = info.get("levels", {}) if isinstance(info, Mapping) else {}
    for level_name, level in (levels or {}).items():
        if not isinstance(level, Mapping):
            continue
        setters = level.get("setters", {})
        setter_list = (
            [_setter_summary(s) for s in setters.values() if isinstance(s, Mapping)]
            if isinstance(setters, Mapping)
            else []
        )
        levels_out[level_name] = {
            "setters": setter_list,
            "setting_method": level.get("setting_method"),
            "getters": [
                g for g in (level.get("getters") or []) if str(g).lower() not in {"none", "void"}
            ],
            "settle_time": level.get("settle_time"),
            "manual_set_before": level.get("manual_set_before") or [],
            "manual_set_after": level.get("manual_set_after") or [],
        }
    return {
        "name": info.get("name") if isinstance(info, Mapping) else None,
        "comments": info.get("comments", "") if isinstance(info, Mapping) else "",
        "levels": levels_out,
    }


PREVIOUS_ANSWERS_LIMIT = 20


def is_stale_item(item: Mapping) -> bool:
    """Items from older prompt versions that should not be reused
    (confirmation questions were folded into the conclusions)."""

    return str(item.get("id", "")).startswith("confirm_") or item.get("origin") == "inference"


def previous_answers(items: Iterable[Mapping] | None) -> list[dict]:
    """The latest answer per field (items come newest first), without
    stale or duplicate entries."""

    out = []
    seen = set()
    for item in items or ():
        if not isinstance(item, Mapping) or is_stale_item(item):
            continue
        if item.get("status") not in (STATUS_ANSWERED, STATUS_UNKNOWN, STATUS_PREFILLED):
            continue
        keys = {item.get("id"), _label_key(item.get("text"))} - {None, ""}
        if keys & seen:
            continue
        seen |= keys
        out.append(
            {
                "id": item.get("id"),
                "text": item.get("text"),
                "answer": item.get("answer") if item.get("status") != STATUS_UNKNOWN else "unknown",
            }
        )
        if len(out) >= PREVIOUS_ANSWERS_LIMIT:
            break
    return out


def build_prompt(
    *,
    mode: str,
    plan: list[dict],
    snapshot: Mapping | None,
    description: Mapping | None,
    previous: list[dict],
    lab_context: str,
    suggestions: str,
    previous_corrections: list[dict] | None = None,
) -> tuple[str, str]:
    """Return (system, user) prompt text.

    The system text holds only stable content (preamble + lab files) so it
    can be cached across scans; everything that changes goes in the user
    message.
    """

    fields = ", ".join(name for name, _label in INFERENCE_FIELDS)
    system = (
        SYSTEM_PREAMBLE.format(max_questions=MAX_QUESTIONS, inference_fields=fields)
        + "\n\n=== lab_context.md ===\n"
        + (lab_context.strip() or "(empty)")
        + "\n\n=== suggested_questions.md ===\n"
        + (suggestions.strip() or "(empty)")
    )
    request = {
        "mode": mode,
        "plan": plan,
        "instrument_snapshot": snapshot or {},
        "experiment_description": dict(description or {}),
        "previous_answers": previous,
        "previous_corrections": previous_corrections or [],
    }
    if mode == "queue":
        lead = (
            "Write ONE questionnaire covering every scan in this queue. The plan lists "
            "queued scans and manual-set steps in run order."
        )
    else:
        lead = "Write the questionnaire for this scan."
    user = lead + "\n\n" + json.dumps(request, separators=(",", ":"), default=str)
    return system, user


# ------------------------------------------------------------ suggestions --

_OFTEN = re.compile(r"\((often|always)\)\s*$", re.IGNORECASE)


def parse_suggestions(text: str) -> list[dict]:
    """Questions from suggested_questions.md: ``- label`` bullet lines, or
    ``- label: a / b / c`` to offer answers.

    ``## heading`` lines name a group, used to build stable ids; a group
    whose name contains "setup" goes in the setup section.
    """

    items = []
    group = "general"
    seen = set()
    for raw in text.splitlines():
        line = raw.strip()
        if line.startswith("#"):
            group = re.sub(r"[^a-z0-9]+", "_", line.lstrip("#").strip().lower()).strip("_") or group
            continue
        if not line.startswith(("- ", "* ")):
            continue
        question = _OFTEN.sub("", line[2:]).strip()
        options = []
        label, sep, choices = question.partition(":")
        if sep and "/" in choices:
            question = label.strip()
            options = [c.strip() for c in choices.split("/") if c.strip()]
        if not question:
            continue
        slug = re.sub(r"[^a-z0-9]+", "_", question.lower()).strip("_")[:40]
        item_id = f"{group}_{slug}"
        if item_id in seen:
            continue
        seen.add(item_id)
        items.append(
            {
                "id": item_id,
                "text": question,
                "section": "setup" if "setup" in group else "scan",
                "kind": "text",
                "unit": "",
                "options": options,
                "prefill": "",
                "reason": f"suggested list ({group})",
            }
        )
    return items[:MAX_QUESTIONS]


# ------------------------------------------------------------------ items --

def _label_key(text) -> str:
    return str(text or "").strip().rstrip("?").strip().lower()


def _match_previous(item: Mapping, previous_items: Iterable[Mapping]) -> Mapping | None:
    by_id = None
    by_text = None
    for old in previous_items or ():
        if not isinstance(old, Mapping):
            continue
        if old.get("id") and old.get("id") == item.get("id"):
            by_id = old
        elif _label_key(old.get("text")) == _label_key(item.get("text")):
            by_text = old
    return by_id or by_text


def normalize_items(
    raw_items: Iterable[Mapping],
    *,
    origin: str,
    previous_items: Iterable[Mapping] | None = None,
) -> list[dict]:
    """Clean model or suggestion output into stored questionnaire items."""

    items = []
    used_ids = set()
    previous_items = list(previous_items or ())
    for raw in raw_items:
        if not isinstance(raw, Mapping):
            continue
        text = str(raw.get("text", "")).strip()
        if not text:
            continue
        kind = raw.get("kind") if raw.get("kind") in QUESTION_KINDS else (
            "choice" if raw.get("options") else "text"
        )
        item_id = re.sub(r"[^A-Za-z0-9_]+", "_", str(raw.get("id") or text.lower()))[:60] or "q"
        base, n = item_id, 2
        while item_id in used_ids:
            item_id = f"{base}_{n}"
            n += 1
        used_ids.add(item_id)
        item = {
            "id": item_id,
            "text": text.rstrip("?").strip() or text,
            "section": raw.get("section") if raw.get("section") in SECTIONS else "scan",
            "kind": kind,
            "unit": str(raw.get("unit", "") or ""),
            "options": [str(o) for o in (raw.get("options") or []) if str(o).strip()],
            "reason": str(raw.get("reason", "") or ""),
            "origin": origin,
            "answer": None,
            "status": STATUS_NOT_ANSWERED,
        }
        old = _match_previous(item, previous_items)
        prefill = str(raw.get("prefill", "") or "").strip()
        if old is not None and old.get("status") == STATUS_UNKNOWN:
            item["status"] = STATUS_PREFILLED
            item["answer"] = "unknown"
        elif old is not None and old.get("answer") not in (None, ""):
            item["status"] = STATUS_PREFILLED
            item["answer"] = str(old.get("answer"))
        elif prefill:
            item["status"] = STATUS_PREFILLED
            item["answer"] = prefill
        items.append(item)
        if len(items) >= MAX_QUESTIONS:
            break
    return items


# ------------------------------------------------------------- inferences --

def inference_label(field: str) -> str:
    if field.startswith("role:"):
        return f"Role of {field[5:]}"
    if field.startswith("axis:"):
        return f"Swept axis {field[5:]}"
    for name, label in INFERENCE_FIELDS:
        if name == field:
            return label
    return field.replace("_", " ").capitalize()


def normalize_inferences(raw_items: Iterable[Mapping]) -> list[dict]:
    """Clean the model's conclusions into stored items (one per field+scope)."""

    out = []
    seen = set()
    for raw in raw_items or ():
        if not isinstance(raw, Mapping):
            continue
        field = re.sub(r"\s+", "_", str(raw.get("field", "")).strip())[:80]
        value = str(raw.get("value", "")).strip()
        if not field or not value:
            continue
        confidence = raw.get("confidence") if raw.get("confidence") in CONFIDENCE_LEVELS else "medium"
        scope = str(raw.get("scope", "") or "scan").strip() or "scan"
        key = (field, scope)
        if key in seen:
            continue
        seen.add(key)
        slug = re.sub(r"[^A-Za-z0-9_]+", "_", field).strip("_")[:50] or "fact"
        out.append(
            {
                "id": f"inf_{slug}" if scope in ("scan", "queue") else f"inf_{slug}__{len(out)}",
                "field": field,
                "value": value,
                "basis": str(raw.get("basis", "") or ""),
                "confidence": confidence,
                "scope": scope,
                "status": INFERENCE_MODEL,
                "model_value": value,
            }
        )
    return out


def set_inference_value(inference: dict, value: str, *, confirmed: bool = False) -> None:
    """Store the user's value; an unchanged value stays the model's (or
    ``user_confirmed`` when the user ticked it as correct)."""

    value = value.strip()
    inference["value"] = value
    if value != inference.get("model_value"):
        inference["status"] = INFERENCE_CORRECTED
    elif confirmed:
        inference["status"] = INFERENCE_CONFIRMED
    else:
        inference["status"] = INFERENCE_MODEL


def needs_check(inference: Mapping) -> bool:
    """A medium-confidence conclusion the user has not looked at yet."""

    return inference.get("confidence") == "medium" and inference.get("status") == INFERENCE_MODEL


def previous_corrections(inferences: Iterable[Mapping] | None) -> list[dict]:
    return [
        {
            "field": inf.get("field"),
            "model_said": inf.get("model_value"),
            "user_value": inf.get("value") if inf.get("status") == INFERENCE_CORRECTED else None,
            "status": inf.get("status"),
        }
        for inf in inferences or ()
        if isinstance(inf, Mapping)
        and inf.get("status") in (INFERENCE_CORRECTED, INFERENCE_REJECTED)
    ]


def inferences_for_scan(inferences: Iterable[Mapping], scan_name: str) -> list[dict]:
    """Queue conclusions that apply to one scan: shared ones plus its own."""

    return copy.deepcopy(
        [
            dict(inf)
            for inf in inferences or ()
            if inf.get("scope") in ("queue", "scan", scan_name)
        ]
    )


def copy_items_for_scan(items: Iterable[Mapping]) -> list[dict]:
    return copy.deepcopy([dict(item) for item in items])


# ------------------------------------------------------------- model call --

class QuestionnaireUnavailable(RuntimeError):
    """The model could not produce questions; the caller falls back.

    ``raw`` holds the model's reply text when there was one.
    """

    def __init__(self, message: str, raw: str | None = None):
        super().__init__(message)
        self.raw = raw


def call_model(
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    provider: str = profile.PROVIDER_ANTHROPIC,
    effort: str = profile.DEFAULT_EFFORT,
    thinking: bool = profile.DEFAULT_THINKING,
    base_url: str | None = None,
    timeout_s: float = 180.0,
) -> dict:
    """Ask the chosen provider; returns ``{"questions": [...], "inferences": [...]}``."""

    if not api_key:
        raise QuestionnaireUnavailable("no API key set")
    url = _resolve_base_url(provider, base_url)
    if provider == profile.PROVIDER_ANTHROPIC:
        # Claude's OpenAI-compatible endpoint ignores response_format and
        # reasoning_effort; effort is passed as the native field and dropped
        # again if the endpoint refuses it.
        return _call_openai_compatible(
            api_key, model, system, user, base_url=url, timeout_s=timeout_s,
            json_mode=False,
            extra_body={"output_config": {"effort": effort}},
        )
    extra_body = None
    if provider == profile.PROVIDER_DEEPSEEK:
        # Dropped again (like the other extras) if the endpoint refuses it.
        extra_body = {"thinking": {"type": "enabled" if thinking else "disabled"}}
    return _call_openai_compatible(
        api_key, model, system, user, base_url=url, timeout_s=timeout_s, extra_body=extra_body
    )


def _usage_text(response, max_tokens: int) -> str:
    usage = getattr(response, "usage", None)
    used = getattr(usage, "completion_tokens", None)
    details = getattr(usage, "completion_tokens_details", None)
    reasoning = getattr(details, "reasoning_tokens", None)
    text = f"{used if used is not None else '?'} of {max_tokens} output tokens"
    if reasoning:
        text += f", {reasoning} spent thinking"
    return text


def _parse_reply(text: str) -> dict:
    raw = text
    text = text.strip()
    fenced = re.match(r"^```(?:json)?\s*(.*?)\s*```$", text, re.DOTALL)
    if fenced:
        text = fenced.group(1)
    try:
        data = json.loads(text)
    except ValueError as exc:
        raise QuestionnaireUnavailable("the model returned invalid JSON", raw) from exc
    questions = data.get("questions") if isinstance(data, dict) else None
    if not isinstance(questions, list):
        raise QuestionnaireUnavailable("the model returned no questions", raw)
    inferences = data.get("inferences")
    return {
        "questions": questions,
        "inferences": inferences if isinstance(inferences, list) else [],
        "_raw": raw,
    }


JSON_SCHEMA_NOTE = (
    "\n\nReply with one JSON object only, no other text, matching this JSON schema:\n"
)


def _resolve_base_url(provider: str, base_url: str | None) -> str:
    url = (base_url or "").strip() or profile.provider_info(provider).get("base_url", "")
    if not url:
        raise QuestionnaireUnavailable("no base URL set for this provider (Setup capture settings)")
    return url


def _call_openai_compatible(
    api_key: str,
    model: str,
    system: str,
    user: str,
    *,
    base_url: str,
    timeout_s: float,
    max_tokens: int = MAX_OUTPUT_TOKENS,
    json_mode: bool = True,
    extra_body: dict | None = None,
) -> dict:
    """One chat-completions call through the openai SDK (Claude, DeepSeek or
    any OpenAI-compatible provider).

    None of these enforce the schema, so it goes into the prompt and the
    reply is checked by ``_parse_reply``.
    """

    if not model:
        raise QuestionnaireUnavailable("no model name set for this provider")

    try:
        import openai
    except Exception as exc:  # noqa: BLE001
        raise QuestionnaireUnavailable(f"openai package not installed ({exc})") from exc

    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=timeout_s,
        max_retries=1,
    )
    request = {
        "model": model,
        "max_tokens": max_tokens,
        "messages": [
            {"role": "system", "content": system + JSON_SCHEMA_NOTE + json.dumps(QUESTION_SCHEMA)},
            {"role": "user", "content": user},
        ],
    }
    if json_mode and "reasoner" not in model:
        request["response_format"] = {"type": "json_object"}
    if extra_body:
        request["extra_body"] = extra_body
    try:
        while True:
            try:
                response = client.chat.completions.create(**request)
                break
            except openai.BadRequestError:
                # Drop optional extras a provider refuses (JSON mode, native
                # effort); the prompt still asks for JSON.
                optional = [key for key in ("extra_body", "response_format") if key in request]
                if not optional:
                    raise
                request.pop(optional[0])
    except openai.AuthenticationError as exc:
        raise QuestionnaireUnavailable("API key rejected") from exc
    except openai.RateLimitError as exc:
        raise QuestionnaireUnavailable("rate limited or out of credit, try again later") from exc
    except openai.APIStatusError as exc:
        raise QuestionnaireUnavailable(f"API error {exc.status_code}: {exc.message}") from exc
    except openai.APIConnectionError as exc:
        raise QuestionnaireUnavailable(f"network error: {exc}") from exc

    if not response.choices:
        raise QuestionnaireUnavailable("the model returned no answer")
    choice = response.choices[0]
    content = choice.message.content or ""
    if choice.finish_reason == "length":
        raise QuestionnaireUnavailable(
            f"the answer was cut off ({_usage_text(response, max_tokens)})", content
        )
    if choice.finish_reason == "content_filter":
        raise QuestionnaireUnavailable("the model declined this request", content)
    reply = _parse_reply(content)
    reply["_usage"] = _usage_text(response, max_tokens)
    return reply


def test_api_key(
    api_key: str,
    model: str,
    provider: str = profile.PROVIDER_ANTHROPIC,
    base_url: str | None = None,
) -> str:
    """One tiny request; returns "OK" or raises QuestionnaireUnavailable."""

    if not api_key:
        raise QuestionnaireUnavailable("no API key set")
    return _test_openai_compatible_key(api_key, model, _resolve_base_url(provider, base_url))


def _test_openai_compatible_key(api_key: str, model: str, base_url: str) -> str:
    if not model:
        raise QuestionnaireUnavailable("no model name set for this provider")
    try:
        import openai
    except Exception as exc:  # noqa: BLE001
        raise QuestionnaireUnavailable(f"openai package not installed ({exc})") from exc
    client = openai.OpenAI(
        api_key=api_key,
        base_url=base_url,
        timeout=30.0,
        max_retries=0,
    )
    try:
        client.chat.completions.create(
            model=model,
            max_tokens=16,
            messages=[{"role": "user", "content": "Reply with OK."}],
        )
    except openai.AuthenticationError as exc:
        raise QuestionnaireUnavailable("API key rejected") from exc
    except openai.APIStatusError as exc:
        raise QuestionnaireUnavailable(f"API error {exc.status_code}: {exc.message}") from exc
    except openai.APIConnectionError as exc:
        raise QuestionnaireUnavailable(f"network error: {exc}") from exc
    return "OK"


def generate(
    *,
    mode: str,
    plan: list[dict],
    snapshot: Mapping | None,
    description: Mapping | None,
    previous_items: list[Mapping],
    api_key: str,
    model: str,
    lab_folder=None,
    model_call: Callable[..., dict] = call_model,
    previous_inferences: list[Mapping] | None = None,
    provider: str = profile.PROVIDER_ANTHROPIC,
    effort: str = profile.DEFAULT_EFFORT,
    thinking: bool = profile.DEFAULT_THINKING,
    base_url: str | None = None,
) -> dict:
    """Produce a questionnaire record; never raises."""

    lab_text = profile.lab_context_text(lab_folder)
    suggestion_text = profile.suggested_questions_text(lab_folder)
    record = {
        "generated_at": now_text(),
        "provider": provider,
        "effort": effort if provider == profile.PROVIDER_ANTHROPIC else None,
        "thinking": thinking if provider == profile.PROVIDER_DEEPSEEK else None,
        "model": None,
        "prompt_version": PROMPT_VERSION,
        "lab_context_version": profile.lab_context_version(lab_text),
        "source": None,
        "error": None,
        "inferences": [],
        "items": [],
    }
    debug = {"system": None, "user": None, "raw": None, "usage": None, "elapsed_s": None}
    started = time.monotonic()
    try:
        system, user = build_prompt(
            mode=mode,
            plan=plan,
            snapshot=snapshot,
            description=description,
            previous=previous_answers(previous_items),
            lab_context=lab_text,
            suggestions=suggestion_text,
            previous_corrections=previous_corrections(previous_inferences),
        )
        debug["system"], debug["user"] = system, user
        if model_call is call_model:
            raw = call_model(
                api_key, model, system, user, provider=provider, effort=effort,
                thinking=thinking, base_url=base_url,
            )
        else:
            raw = model_call(api_key, model, system, user)
        if isinstance(raw, Mapping):
            debug["raw"] = raw.get("_raw")
            debug["usage"] = raw.get("_usage")
            raw_questions = raw.get("questions") or []
            raw_inferences = raw.get("inferences") or []
        else:  # older callers return only the question list
            raw_questions, raw_inferences = raw, []
        record["inferences"] = normalize_inferences(raw_inferences)
        record["items"] = normalize_items(
            raw_questions, origin="agent", previous_items=previous_items
        )
        record["model"] = model
        record["source"] = "agent"
        if not record["items"]:
            raise QuestionnaireUnavailable("the model returned no usable questions")
    except Exception as exc:  # noqa: BLE001 - always fall back
        record["error"] = str(exc) if isinstance(exc, QuestionnaireUnavailable) else f"{type(exc).__name__}: {exc}"
        debug["raw"] = debug["raw"] or getattr(exc, "raw", None)
        record["model"] = None
        record["source"] = "suggestions"
        record["inferences"] = []
        record["items"] = normalize_items(
            parse_suggestions(suggestion_text), origin="suggestion", previous_items=previous_items
        )
    debug["elapsed_s"] = round(time.monotonic() - started, 1)
    # Not part of the saved record; pop it before storing (see model_output_markdown).
    record[DEBUG_KEY] = debug
    return record


def model_output_markdown(record: Mapping, debug: Mapping, *, title: str) -> str:
    """Readable dump of one model run: summary, parsed result, raw reply, prompt."""

    clean = {k: v for k, v in record.items() if k != DEBUG_KEY}
    lines = [
        f"# Questionnaire model output: {title}",
        "",
        f"- Generated: {record.get('generated_at')}",
        f"- Provider / model: {record.get('provider')} / {record.get('model') or '-'}"
        + (f" (effort {record['effort']})" if record.get("effort") else "")
        + (f" (thinking {'on' if record['thinking'] else 'off'})" if record.get("thinking") is not None else ""),
        f"- Source: {record.get('source')}",
        f"- Time: {debug.get('elapsed_s')} s",
        f"- Output tokens: {debug.get('usage') or '-'}",
        f"- Error: {record.get('error') or '-'}",
        f"- Prompt version: {record.get('prompt_version')}, {record.get('lab_context_version')}",
        "",
        "## Conclusions",
        "",
    ]
    for inf in clean.get("inferences") or []:
        lines.append(
            f"- **{inference_label(str(inf.get('field', '')))}**: {inf.get('value')} "
            f"({inf.get('confidence')}; basis: {inf.get('basis') or '-'}; scope: {inf.get('scope')})"
        )
    if not clean.get("inferences"):
        lines.append("(none)")
    lines += ["", "## Fields", ""]
    for item in clean.get("items") or []:
        extra = []
        if item.get("unit"):
            extra.append(item["unit"])
        if item.get("options"):
            extra.append(" / ".join(item["options"]))
        if item.get("answer") not in (None, ""):
            extra.append(f"prefilled: {item['answer']}")
        suffix = f" ({'; '.join(extra)})" if extra else ""
        lines.append(f"- [{item.get('section', 'scan')}] **{item.get('text')}**{suffix}")
        if item.get("reason"):
            lines.append(f"  - reason: {item['reason']}")
    lines += [
        "",
        "## Raw model reply",
        "",
        "```",
        str(debug.get("raw") or "(no reply)"),
        "```",
        "",
        "## Prompt: user message",
        "",
        "```",
        _pretty_user_prompt(str(debug.get("user") or "")),
        "```",
        "",
        "## Prompt: system message",
        "",
        "```",
        str(debug.get("system") or ""),
        "```",
        "",
    ]
    return "\n".join(lines)


def _pretty_user_prompt(text: str) -> str:
    """The user message is sent as compact JSON; indent it for reading."""

    lead, sep, body = text.partition("\n\n")
    try:
        return lead + sep + json.dumps(json.loads(body), indent=1, ensure_ascii=False)
    except ValueError:
        return text


def save_model_output(record: dict, folder: str, name: str) -> str | None:
    """Pop the debug data from ``record`` and, when a model call was made,
    write it to ``<folder>/<name>_questionnaire_<time>.md``.  Returns the
    path, or None when nothing was written."""

    debug = record.pop(DEBUG_KEY, None)
    if not SAVE_MODEL_OUTPUT or not isinstance(debug, Mapping) or not debug.get("user"):
        return None
    if "no API key" in str(record.get("error") or ""):
        return None  # the model was never called
    safe = re.sub(r"[^A-Za-z0-9._-]+", "_", name or "scan").strip("_") or "scan"
    stamp = _dt.datetime.now().strftime("%Y%m%d_%H%M%S")
    os.makedirs(folder, exist_ok=True)
    path = os.path.join(folder, f"{safe}_questionnaire_{stamp}.md")
    with open(path, "w", encoding="utf-8") as handle:
        handle.write(model_output_markdown(record, debug, title=name or safe))
    return path


class QuestionnaireWorker(QtCore.QObject):
    """Runs a job (snapshot and/or model call) on a daemon thread.

    ``sig_done`` is delivered on the thread that owns this object (the UI
    thread).  A daemon thread is used instead of a QThread so a slow model
    call never blocks or crashes application exit.
    """

    sig_done = QtCore.pyqtSignal(object)

    def __init__(self, *, job: Callable[[], dict], parent=None):
        super().__init__(parent)
        self._job = job
        self._thread = None

    def start(self) -> None:
        self._thread = threading.Thread(
            target=self._run, name="SetupQuestionnaire", daemon=True
        )
        self._thread.start()

    def is_running(self) -> bool:
        return self._thread is not None and self._thread.is_alive()

    def wait(self, timeout_ms: int) -> None:
        if self._thread is not None:
            self._thread.join(max(0, timeout_ms) / 1000.0)

    def _run(self) -> None:
        try:
            result = self._job()
        except Exception as exc:  # noqa: BLE001
            result = {"error": f"{type(exc).__name__}: {exc}", "items": [], "source": "error"}
        try:
            self.sig_done.emit(result)
        except RuntimeError:
            pass  # owner was deleted while the job ran
