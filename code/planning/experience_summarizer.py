from __future__ import annotations

import json
from typing import Any, Optional


def build_experience_summary_prompt(
    category: str,
    run_summary: dict[str, Any],
    page_semantics: Optional[list[str]] = None,
) -> str:
    """
    Build a single prompt string for experience summarization.

    This prompt is directly used for manual GPT interaction.
    """
    summary_input = build_summary_input(
        category=category,
        run_summary=run_summary,
        page_semantics=page_semantics,
    )

    summary_input_json = json.dumps(
        summary_input,
        ensure_ascii=False,
        separators=(",", ":"),
    )

    return (
        "You are an expert at summarizing successful mobile GUI interaction flows into reusable high-level experience memories.\n"
        "Given one successful execution trace, summarize it into reusable high-level steps.\n"
        "Do NOT output low-level actions like click node_xx.\n"
        "Do NOT mention node ids.\n"
        "Use the action reasons as the main semantic evidence.\n"
        "Steps must be abstract, short, and reusable across similar apps.\n"
        "Return JSON only.\n\n"
        f"Input:\n{summary_input_json}\n\n"
        "Output JSON format:\n"
        '{"category":"","function_summary":"","experience_steps":["",""],"abstraction_note":""}'
    )


def build_summary_input(
    category: str,
    run_summary: dict[str, Any],
    page_semantics: Optional[list[str]] = None,
) -> dict[str, Any]:
    """
    Extract minimal necessary information from run_summary.
    """
    memory = run_summary.get("memory", {})
    action_history = memory.get("action_history", [])

    compact_actions = compact_action_history(action_history)

    if page_semantics is None:
        page_semantics = []

    return {
        "category": str(category).strip(),
        "actions": compact_actions,
        "pages": [str(x).strip() for x in page_semantics if str(x).strip() != ""],
    }


def compact_action_history(
    action_history: list[dict[str, Any]],
) -> list[dict[str, Any]]:
    """
    Keep action type and semantic reason for experience summarization.
    """
    result: list[dict[str, Any]] = []

    for action in action_history:
        item = {
            "type": action.get("action_type"),
        }

        input_text = str(action.get("input_text", "") or "").strip()
        if input_text != "":
            item["input"] = input_text

        reason = str(action.get("reason", "") or "").strip()
        if reason != "":
            item["reason"] = reason

        result.append(item)

    return result