from __future__ import annotations

import json
import math
from copy import deepcopy
from typing import Any, Optional


MAX_PROMPT_COMPONENTS = 28
MAX_LABEL_TEXTS_PER_ACTIONABLE = 2
LABEL_DISTANCE_THRESHOLD = 220.0


def build_gpt_prompt_package(
    ui_state: dict[str, Any],
    memory: Optional[Any] = None,
) -> dict[str, Any]:
    """
    Build a GPT prompt package for GUI action planning.

    Output schema:
    {
        "mode": "manual_llm_planning_api_prompt",
        "screenshot_path": str,
        "system_prompt": str,
        "user_prompt": str,
        "component_brief": list[dict],
        "memory_summary": dict,
        "response_format": dict
    }
    """
    components = ui_state.get("components", [])
    screenshot_path = ui_state.get("screenshot_path", "")

    component_brief = build_component_brief(components)
    memory_summary = build_memory_summary(memory)
    user_prompt = build_user_prompt(
        component_brief=component_brief,
        memory_summary=memory_summary,
        screenshot_path=screenshot_path,
    )
    response_format = build_response_format_schema()

    return {
        "mode": "manual_llm_planning_api_prompt",
        "screenshot_path": screenshot_path,
        "system_prompt": "",
        "user_prompt": user_prompt,
        "component_brief": component_brief,
        "memory_summary": memory_summary,
        "response_format": response_format,
    }


def build_user_prompt(
    component_brief: list[dict[str, Any]],
    memory_summary: dict[str, Any],
    screenshot_path: str,
) -> str:
    """
    Build the merged prompt for GPT-based GUI planning.
    """
    component_json = json.dumps(component_brief, ensure_ascii=False, separators=(",", ":"))
    memory_json = json.dumps(memory_summary, ensure_ascii=False, separators=(",", ":"))

    return (
        "You are a mobile GUI action planner.\n"
        "Given the current page, choose exactly one next action and return JSON only.\n"
        "target_id must come from the component list.\n"
        "action_type must be one of click,input,scroll,wait,stop.\n"
        "For input, input_text must be non-empty. Otherwise input_text must be ''.\n"
        "Use wait for loading or temporarily unavailable pages.\n"
        "Do not repeat the same ineffective action when the last action had no UI change.\n"
        "Do not submit too early if required fields are still unfilled.\n"
        "Use scroll only when more content likely needs to be revealed.\n"
        "Set is_complete=true only if the task is finished or no meaningful action remains.\n"
        "If is_complete=true, action_type must be stop and target_id must be null.\n"
        "Important: for click actions, prefer components with clk=true or actionable types such as Button/Clickable/Dropdown/Selection.\n"
        "Important: Text components without clk=true are usually labels, not click targets.\n"
        "Component key legend: "
        "id=target_id,tp=type,tx=text,cd=content_desc,rid=resource_id,lbl=merged nearby label,"
        "clk=clickable,scr=scrollable,chk=checked,sel=selected,bd=bounds.\n\n"
        f"Screen:\n{screenshot_path}\n\n"
        f"Components:\n{component_json}\n\n"
        f"Memory:\n{memory_json}\n\n"
        "Return JSON:\n"
        '{"page_understanding":"","next_action":{"action_type":"","target_id":null,"input_text":"","reason":""},"is_complete":false}'
    )


def build_component_brief(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Build a concise component list for GPT.
    """
    relevant_components = []
    for component in components:
        if not is_component_prompt_relevant(component):
            continue
        relevant_components.append(deepcopy(component))

    enrich_actionable_components_with_labels(relevant_components)

    scored_components: list[tuple[int, dict[str, Any]]] = []

    for component in relevant_components:
        compact_component = build_compact_component(component)
        score = score_component_for_prompt(component)
        scored_components.append((score, compact_component))

    scored_components.sort(key=lambda item: item[0], reverse=True)

    brief_components = [item[1] for item in scored_components[:MAX_PROMPT_COMPONENTS]]
    return brief_components


def build_compact_component(component: dict[str, Any]) -> dict[str, Any]:
    """
    Build a compact component representation for prompting.
    """
    compact_component: dict[str, Any] = {
        "id": component.get("id"),
        "tp": component.get("type"),
    }

    text = normalize_text(component.get("text"))
    content_desc = normalize_text(component.get("content_desc"))
    resource_id = normalize_text(component.get("resource_id"))
    merged_label = normalize_text(component.get("merged_label"))

    if text:
        compact_component["tx"] = text

    if content_desc:
        compact_component["cd"] = content_desc

    if resource_id:
        compact_component["rid"] = resource_id

    if merged_label:
        compact_component["lbl"] = merged_label

    if should_keep_clickable_flag(component):
        compact_component["clk"] = bool(component.get("clickable", False))

    if should_keep_scrollable_flag(component):
        compact_component["scr"] = bool(component.get("scrollable", False))

    if should_keep_checked_flag(component):
        compact_component["chk"] = bool(component.get("checked", False))

    if should_keep_selected_flag(component):
        compact_component["sel"] = bool(component.get("selected", False))

    if should_keep_bounds(component):
        compact_component["bd"] = compact_bounds(component.get("bounds"))

    return compact_component


def enrich_actionable_components_with_labels(components: list[dict[str, Any]]) -> None:
    """
    Merge nearby text labels into actionable components so GPT can see
    which clickable target corresponds to visible text like 'Next'.
    """
    actionable_components = [c for c in components if is_actionable_candidate(c)]
    text_components = [c for c in components if is_text_label_candidate(c)]

    assigned_texts: dict[str, list[str]] = {}

    for text_component in text_components:
        text_value = get_text_label_value(text_component)
        if text_value == "":
            continue

        best_actionable = None
        best_score = -1.0

        for actionable_component in actionable_components:
            relation_score = score_text_to_actionable_relation(
                text_component=text_component,
                actionable_component=actionable_component,
            )
            if relation_score > best_score:
                best_score = relation_score
                best_actionable = actionable_component

        if best_actionable is None:
            continue

        if best_score < 0:
            continue

        actionable_id = str(best_actionable.get("id"))
        assigned_texts.setdefault(actionable_id, [])

        if text_value not in assigned_texts[actionable_id]:
            if len(assigned_texts[actionable_id]) < MAX_LABEL_TEXTS_PER_ACTIONABLE:
                assigned_texts[actionable_id].append(text_value)

    for component in components:
        component_id = str(component.get("id"))
        labels = assigned_texts.get(component_id, [])
        if labels:
            component["merged_label"] = " | ".join(labels)


def score_text_to_actionable_relation(
    text_component: dict[str, Any],
    actionable_component: dict[str, Any],
) -> float:
    """
    Score how likely a text node is the label of an actionable component.
    Larger is better.
    """
    text_bounds = text_component.get("bounds")
    actionable_bounds = actionable_component.get("bounds")

    if not is_valid_bounds(text_bounds) or not is_valid_bounds(actionable_bounds):
        return -1.0

    text_center = get_bounds_center(text_bounds)
    actionable_center = get_bounds_center(actionable_bounds)
    distance = euclidean_distance(text_center, actionable_center)

    if distance > LABEL_DISTANCE_THRESHOLD:
        return -1.0

    vertical_overlap = get_vertical_overlap_ratio(text_bounds, actionable_bounds)
    horizontal_overlap = get_horizontal_overlap_ratio(text_bounds, actionable_bounds)

    score = 0.0

    score += max(0.0, LABEL_DISTANCE_THRESHOLD - distance)
    score += vertical_overlap * 120.0
    score += horizontal_overlap * 60.0

    text_y = text_center[1]
    actionable_y = actionable_center[1]
    if abs(text_y - actionable_y) <= 120:
        score += 40.0

    text_x = text_center[0]
    actionable_x = actionable_center[0]
    if abs(text_x - actionable_x) <= 160:
        score += 20.0

    return score


def is_component_prompt_relevant(component: dict[str, Any]) -> bool:
    """
    Decide whether a component should be included in the GPT prompt.
    """
    if not component.get("visible", False):
        return False

    if not component.get("enabled", False):
        return False

    if is_ad_component(component):
        return False

    component_type = component.get("type")
    class_name = str(component.get("class_name", "") or "").lower()
    text = normalize_text(component.get("text"))
    content_desc = normalize_text(component.get("content_desc"))
    resource_id = normalize_text(component.get("resource_id"))
    clickable = bool(component.get("clickable", False))
    scrollable = bool(component.get("scrollable", False))

    has_semantic_text = bool(text or content_desc or resource_id)

    if component_type == "Text":
        if not has_semantic_text:
            return False
        if is_tiny_or_meaningless_text(text, content_desc, resource_id):
            return False
        return True

    if component_type in {"Input", "Button", "Dropdown", "Selection", "ScrollContainer"}:
        return True

    if component_type == "Clickable":
        if has_semantic_text:
            return True
        if clickable and is_meaningful_container(component):
            return True
        return False

    if scrollable:
        return True

    if clickable and has_semantic_text:
        return True

    if component_type == "Other":
        if "webview" in class_name or "compose" in class_name:
            return has_semantic_text
        return False

    return False


def score_component_for_prompt(component: dict[str, Any]) -> int:
    """
    Score components so that more important ones are kept first when truncated.
    """
    score = 0

    component_type = component.get("type")
    text = normalize_text(component.get("text"))
    content_desc = normalize_text(component.get("content_desc"))
    resource_id = normalize_text(component.get("resource_id"))
    merged_label = normalize_text(component.get("merged_label"))

    if component_type == "Input":
        score += 100
    elif component_type == "Button":
        score += 90
    elif component_type == "Dropdown":
        score += 85
    elif component_type == "Selection":
        score += 80
    elif component_type == "ScrollContainer":
        score += 70
    elif component_type == "Clickable":
        score += 60
    elif component_type == "Text":
        score += 40

    if component.get("clickable", False):
        score += 20

    if component.get("scrollable", False):
        score += 15

    if text:
        score += 20

    if content_desc:
        score += 12

    if resource_id:
        score += 8

    if merged_label:
        score += 35

    important_keywords = {
        "search", "next", "continue", "submit", "save", "confirm", "done",
        "login", "sign", "date", "time", "guest", "account", "setting",
        "permission", "allow", "open", "add", "edit", "create", "close"
    }

    text_blob = f"{text} {content_desc} {resource_id} {merged_label}".lower()
    for keyword in important_keywords:
        if keyword in text_blob:
            score += 10

    return score


def is_meaningful_container(component: dict[str, Any]) -> bool:
    """
    Decide whether a clickable container is worth keeping even with weak text.
    """
    bounds = component.get("bounds", [0, 0, 0, 0])
    if not is_valid_bounds(bounds):
        return False

    x1, y1, x2, y2 = bounds
    width = x2 - x1
    height = y2 - y1

    if width >= 300 and height >= 80:
        return True

    return False


def is_tiny_or_meaningless_text(text: str, content_desc: str, resource_id: str) -> bool:
    """
    Filter out meaningless text nodes.
    """
    merged = f"{text} {content_desc} {resource_id}".strip().lower()

    if merged == "":
        return True

    junk_values = {
        "ad",
        "ads",
        "advertisement",
        "ad choices icon",
        "null",
    }

    if merged in junk_values:
        return True

    if len(text) == 0 and len(content_desc) == 0 and len(resource_id) == 0:
        return True

    return False


def is_ad_component(component: dict[str, Any]) -> bool:
    """
    Filter ad-related components aggressively.
    """
    text = normalize_text(component.get("text")).lower()
    content_desc = normalize_text(component.get("content_desc")).lower()
    resource_id = normalize_text(component.get("resource_id")).lower()
    class_name = str(component.get("class_name", "") or "").lower()

    merged = f"{text} {content_desc} {resource_id} {class_name}"

    ad_keywords = {
        "ad choices",
        "ad_choice",
        "advertisement",
        "liftoff",
        "admob",
        "nativead",
        "bannerad",
        "doubleclick",
        "optout.html",
        "call_to_action",
        "headline",
    }

    for keyword in ad_keywords:
        if keyword in merged:
            return True

    if text == "ad":
        return True

    return False


def normalize_text(value: Any) -> str:
    """
    Normalize text-like values.
    """
    if value is None:
        return ""
    return str(value).strip()


def should_keep_clickable_flag(component: dict[str, Any]) -> bool:
    """
    Decide whether clickable should be retained in the compact component.
    """
    component_type = component.get("type")
    if component_type in {"Button", "Clickable", "Selection", "Dropdown"}:
        return True
    return False


def should_keep_scrollable_flag(component: dict[str, Any]) -> bool:
    """
    Decide whether scrollable should be retained in the compact component.
    """
    component_type = component.get("type")
    if component_type == "ScrollContainer":
        return True
    if component.get("scrollable", False):
        return True
    return False


def should_keep_checked_flag(component: dict[str, Any]) -> bool:
    """
    Decide whether checked should be retained in the compact component.
    """
    return component.get("type") == "Selection"


def should_keep_selected_flag(component: dict[str, Any]) -> bool:
    """
    Decide whether selected should be retained in the compact component.
    """
    return component.get("type") in {"Selection", "Dropdown"}


def should_keep_bounds(component: dict[str, Any]) -> bool:
    """
    Decide whether compact bounds should be retained.
    """
    component_type = component.get("type")
    if component_type in {"Button", "Clickable", "Dropdown", "Selection", "Input"}:
        return True

    if normalize_text(component.get("merged_label")):
        return True

    return False


def compact_bounds(bounds: Any) -> list[int]:
    """
    Keep bounds compact and valid.
    """
    if not is_valid_bounds(bounds):
        return [0, 0, 0, 0]

    x1, y1, x2, y2 = bounds
    return [int(x1), int(y1), int(x2), int(y2)]


def is_actionable_candidate(component: dict[str, Any]) -> bool:
    """
    Decide whether a component can be treated as an actionable candidate.
    """
    component_type = component.get("type")

    if component_type in {"Input", "Button", "Dropdown", "Selection", "Clickable"}:
        return True

    if component.get("clickable", False):
        return True

    return False


def is_text_label_candidate(component: dict[str, Any]) -> bool:
    """
    Decide whether a component can be treated as a label candidate.
    """
    if component.get("type") != "Text":
        return False

    text_value = get_text_label_value(component)
    if text_value == "":
        return False

    return True


def get_text_label_value(component: dict[str, Any]) -> str:
    """
    Get the most useful text-like label value from a component.
    """
    text = normalize_text(component.get("text"))
    if text:
        return text

    content_desc = normalize_text(component.get("content_desc"))
    if content_desc:
        return content_desc

    return ""


def is_valid_bounds(bounds: Any) -> bool:
    """
    Check whether bounds are valid.
    """
    if not isinstance(bounds, list) or len(bounds) != 4:
        return False

    return all(isinstance(v, int) for v in bounds)


def get_bounds_center(bounds: list[int]) -> tuple[float, float]:
    """
    Get the center point of bounds.
    """
    x1, y1, x2, y2 = bounds
    return ((x1 + x2) / 2.0, (y1 + y2) / 2.0)


def euclidean_distance(
    point_a: tuple[float, float],
    point_b: tuple[float, float],
) -> float:
    """
    Compute Euclidean distance between two points.
    """
    return math.sqrt((point_a[0] - point_b[0]) ** 2 + (point_a[1] - point_b[1]) ** 2)


def get_vertical_overlap_ratio(bounds_a: list[int], bounds_b: list[int]) -> float:
    """
    Compute vertical overlap ratio between two rectangles.
    """
    a_top = bounds_a[1]
    a_bottom = bounds_a[3]
    b_top = bounds_b[1]
    b_bottom = bounds_b[3]

    overlap = max(0, min(a_bottom, b_bottom) - max(a_top, b_top))
    a_height = max(1, a_bottom - a_top)
    b_height = max(1, b_bottom - b_top)

    return overlap / float(min(a_height, b_height))


def get_horizontal_overlap_ratio(bounds_a: list[int], bounds_b: list[int]) -> float:
    """
    Compute horizontal overlap ratio between two rectangles.
    """
    a_left = bounds_a[0]
    a_right = bounds_a[2]
    b_left = bounds_b[0]
    b_right = bounds_b[2]

    overlap = max(0, min(a_right, b_right) - max(a_left, b_left))
    a_width = max(1, a_right - a_left)
    b_width = max(1, b_right - b_left)

    return overlap / float(min(a_width, b_width))


def build_memory_summary(memory: Optional[Any]) -> dict[str, Any]:
    """
    Build a compact memory summary for GPT.
    """
    if memory is None:
        return {
            "sc": 0,
            "ra": [],
            "lf": None,
            "rh": False,
        }

    step_count = getattr(memory, "step_count", 0)
    recent_actions = []
    last_feedback = getattr(memory, "last_feedback", None)

    if hasattr(memory, "get_recent_actions"):
        raw_recent_actions = memory.get_recent_actions(k=2)
        recent_actions = compact_recent_actions(raw_recent_actions)

    repeated_state_hint = False
    if hasattr(memory, "did_ui_change"):
        did_change = memory.did_ui_change()
        if did_change is False:
            repeated_state_hint = True

    compact_feedback = compact_last_feedback(last_feedback)

    return {
        "sc": step_count,
        "ra": recent_actions,
        "lf": compact_feedback,
        "rh": repeated_state_hint,
    }


def compact_recent_actions(actions: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Keep only the essential fields of recent actions.
    """
    compact_actions: list[dict[str, Any]] = []

    for action in actions:
        compact_action = {
            "a": action.get("action_type"),
            "id": action.get("target_id"),
        }

        input_text = str(action.get("input_text", "") or "")
        if input_text.strip() != "":
            compact_action["txt"] = input_text

        compact_actions.append(compact_action)

    return compact_actions


def compact_last_feedback(last_feedback: Any) -> Optional[dict[str, Any]]:
    """
    Keep only the essential feedback fields for prompt usage.
    """
    if not isinstance(last_feedback, dict):
        return None

    compact_feedback = {
        "ok": bool(last_feedback.get("success", False)),
        "chg": bool(last_feedback.get("ui_changed", False)),
    }

    error_message = str(last_feedback.get("error_message", "") or "").strip()
    if error_message != "":
        compact_feedback["err"] = error_message

    return compact_feedback


def build_response_format_schema() -> dict[str, Any]:
    """
    Define the expected GPT response schema.
    """
    return {
        "page_understanding": "Brief semantic understanding of the current page.",
        "next_action": {
            "action_type": "click | input | scroll | wait | stop",
            "target_id": "must be one id from the provided component list, or null for stop/wait",
            "input_text": "required for input, otherwise empty string",
            "reason": "brief reason for choosing this action",
        },
        "is_complete": False,
    }


def export_prompt_package(prompt_package: dict[str, Any]) -> dict[str, Any]:
    """
    Return a safe exported copy of the prompt package.
    """
    return deepcopy(prompt_package)