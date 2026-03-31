from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional


ALLOWED_ACTION_TYPES = {"click", "input", "scroll", "wait", "stop"}


def build_local_action_from_llm_response(
    llm_response: dict[str, Any],
    ui_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Build a standard LocalAction from an LLM response.

    Expected LLM response schema:
    {
        "page_understanding": "...",
        "next_action": {
            "action_type": "click | input | scroll | wait | stop",
            "target_id": "node_xx" or null,
            "input_text": "...",
            "reason": "..."
        },
        "is_complete": false
    }

    Output LocalAction schema:
    {
        "action_type": "click | input | scroll | wait | stop",
        "target_id": str | None,
        "input_text": str,
        "reason": str
    }
    """
    if not isinstance(llm_response, dict):
        return make_action(
            action_type="stop",
            target_id=None,
            input_text="",
            reason="invalid_llm_response_type",
        )

    next_action = llm_response.get("next_action")
    is_complete = llm_response.get("is_complete", False)

    if is_complete is True:
        return make_action(
            action_type="stop",
            target_id=None,
            input_text="",
            reason="llm_marked_task_complete",
        )

    if not isinstance(next_action, dict):
        return make_action(
            action_type="stop",
            target_id=None,
            input_text="",
            reason="missing_next_action",
        )

    action_type = normalize_action_type(next_action.get("action_type"))
    target_id = normalize_target_id(next_action.get("target_id"))
    input_text = normalize_input_text(next_action.get("input_text"))
    reason = normalize_reason(next_action.get("reason"))

    validation_error = validate_next_action(
        action_type=action_type,
        target_id=target_id,
        input_text=input_text,
        ui_state=ui_state,
    )

    if validation_error is not None:
        return make_action(
            action_type="stop",
            target_id=None,
            input_text="",
            reason=validation_error,
        )

    if action_type == "stop":
        return make_action(
            action_type="stop",
            target_id=None,
            input_text="",
            reason=reason or "llm_requested_stop",
        )

    return make_action(
        action_type=action_type,
        target_id=target_id,
        input_text=input_text,
        reason=reason or "parsed_from_llm_response",
    )


def make_action(
    action_type: str,
    target_id: Optional[str],
    input_text: str,
    reason: str,
) -> dict[str, Any]:
    """
    Construct a LocalAction object.
    """
    return {
        "action_type": action_type,
        "target_id": target_id,
        "input_text": input_text,
        "reason": reason,
    }


def normalize_action_type(value: Any) -> str:
    """
    Normalize action_type to a lowercase string.
    """
    if value is None:
        return ""

    action_type = str(value).strip().lower()
    return action_type


def normalize_target_id(value: Any) -> Optional[str]:
    """
    Normalize target_id.

    For stop action or invalid values, target_id may be None.
    """
    if value is None:
        return None

    target_id = str(value).strip()
    if target_id == "" or target_id.lower() == "null":
        return None

    return target_id


def normalize_input_text(value: Any) -> str:
    """
    Normalize input_text to a string.
    """
    if value is None:
        return ""
    return str(value)


def normalize_reason(value: Any) -> str:
    """
    Normalize reason to a compact string.
    """
    if value is None:
        return ""
    return str(value).strip()


def validate_next_action(
    action_type: str,
    target_id: Optional[str],
    input_text: str,
    ui_state: Optional[dict[str, Any]] = None,
) -> Optional[str]:
    """
    Validate the parsed next action.

    Returns:
    - None if valid
    - error string if invalid
    """
    if action_type not in ALLOWED_ACTION_TYPES:
        return "invalid_action_type"

    if action_type in {"stop", "wait"}:
        return None

    if action_type in {"click", "input", "scroll"} and target_id is None:
        return "missing_target_id_for_non_stop_action"

    if action_type == "input" and input_text.strip() == "":
        return "missing_input_text_for_input_action"

    if action_type in {"click", "scroll"} and input_text.strip() != "":
        return "unexpected_input_text_for_click_or_scroll"

    if ui_state is not None and target_id is not None:
        if not target_exists_in_ui_state(target_id, ui_state):
            return "target_id_not_found_in_ui_state"

        component = find_component_by_id(ui_state.get("components", []), target_id)
        if component is None:
            return "target_component_lookup_failed"

        if not component.get("visible", False):
            return "target_component_not_visible"

        if not component.get("enabled", False):
            return "target_component_not_enabled"

        if action_type == "click" and not is_clickable_like(component):
            return "target_component_not_clickable_for_click_action"

        if action_type == "input" and not is_input_like(component):
            return "target_component_not_input_for_input_action"

        if action_type == "scroll" and not is_scroll_like(component):
            return "target_component_not_scrollable_for_scroll_action"

    return None


def target_exists_in_ui_state(target_id: str, ui_state: dict[str, Any]) -> bool:
    """
    Check whether target_id exists in the current UIState.
    """
    components = ui_state.get("components", [])
    for component in components:
        if component.get("id") == target_id:
            return True
    return False


def find_component_by_id(
    components: list[dict[str, Any]], 
    target_id: str,
) -> Optional[dict[str, Any]]:
    """
    Find a component by id from the component list.
    """
    for component in components:
        if component.get("id") == target_id:
            return deepcopy(component)
    return None


def is_clickable_like(component: dict[str, Any]) -> bool:
    """
    Decide whether the component can serve as a click target.
    """
    component_type = component.get("type")
    clickable = component.get("clickable", False)

    if clickable:
        return True

    if component_type in {"Button", "Clickable", "Selection", "Dropdown"}:
        return True

    return False


def is_input_like(component: dict[str, Any]) -> bool:
    """
    Decide whether the component can serve as an input target.
    """
    component_type = component.get("type")
    class_name = str(component.get("class_name", "") or "").lower()
    resource_id = str(component.get("resource_id", "") or "").lower()
    bounds = component.get("bounds", [0, 0, 0, 0])

    if component_type == "Input":
        return True

    # Rich-text / web-based editor containers
    if "webview" in class_name:
        return True

    if "compose" in class_name:
        return True

    if "edit" in class_name or "editor" in class_name:
        return True

    if "edit" in resource_id or "editor" in resource_id or "content" in resource_id:
        return True

    # Large central regions may serve as editor bodies in note/journal apps
    if component_type in {"Other", "Clickable", "ScrollContainer"}:
        if is_large_component(bounds):
            return True

    return False


def is_scroll_like(component: dict[str, Any]) -> bool:
    """
    Decide whether the component can serve as a scroll target.
    """
    component_type = component.get("type")
    scrollable = component.get("scrollable", False)

    if component_type == "ScrollContainer":
        return True

    if scrollable:
        return True

    return False


def is_large_component(bounds: Any) -> bool:
    """
    Decide whether a component is a large central container that may represent
    an editor body or major content region.
    """
    if not isinstance(bounds, list) or len(bounds) != 4:
        return False

    x1, y1, x2, y2 = bounds
    if not all(isinstance(v, int) for v in bounds):
        return False

    width = x2 - x1
    height = y2 - y1

    if width >= 800 and height >= 600:
        return True

    return False


def build_local_action_from_llm_response_file(
    llm_response_data: dict[str, Any],
    ui_state: Optional[dict[str, Any]] = None,
) -> dict[str, Any]:
    """
    Wrapper helper for controller integration.

    This function exists mainly for readability in the controller layer.
    """
    return build_local_action_from_llm_response(
        llm_response=llm_response_data,
        ui_state=ui_state,
    )


def export_local_action(action: dict[str, Any]) -> dict[str, Any]:
    """
    Return a safe exported copy of the LocalAction.
    """
    return deepcopy(action)