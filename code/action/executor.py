from __future__ import annotations

import time
from copy import deepcopy
from typing import Any, Optional

import uiautomator2 as u2

from perception.extract_components import build_state_signature, dump_ui_state


def execute_action(
    device: u2.Device,
    local_action: dict[str, Any],
    ui_state: dict[str, Any],
    output_dir: str = "tmp",
    wait_after_action: float = 1.0,
) -> dict[str, Any]:
    """
    Execute a LocalAction on the device and return ExecutionFeedback.

    Input:
    - device: connected uiautomator2 device
    - local_action: LocalAction
    - ui_state: current UIState before execution

    Output schema:
    {
        "success": bool,
        "ui_changed": bool,
        "new_signature": str,
        "error_message": str
    }
    """
    action_type = local_action.get("action_type")
    target_id = local_action.get("target_id")

    before_components = ui_state.get("components", [])
    before_signature = build_state_signature(before_components, max_items=200)

    success = False
    error_message = ""

    try:
        if action_type == "click":
            success = execute_click(device, target_id, before_components)

        elif action_type == "input":
            input_text = local_action.get("input_text", "")
            success = execute_input(device, target_id, input_text, before_components)

        elif action_type == "scroll":
            success = execute_scroll(device, target_id, before_components)

        elif action_type == "wait":
            seconds = float(local_action.get("seconds", 2))
            time.sleep(seconds)
            success = True

        elif action_type == "stop":
            success = True

        else:
            error_message = f"unsupported_action_type: {action_type}"
            success = False

    except Exception as exc:
        error_message = f"{type(exc).__name__}: {str(exc)}"
        success = False

    time.sleep(wait_after_action)

    try:
        new_ui_state = dump_ui_state(
            device=device,
            output_dir=output_dir,
            include_system_ui=False,
            export_debug_json=False,
        )
        new_components = new_ui_state.get("components", [])
        new_signature = build_state_signature(new_components, max_items=200)

        ui_changed = detect_ui_changed(
            before_components=before_components,
            after_components=new_components,
            before_signature=before_signature,
            after_signature=new_signature,
            local_action=local_action,
        )

        if action_type == "input" and success:
            input_verified = verify_input_effect(
                before_components=before_components,
                after_components=new_components,
                local_action=local_action,
            )

            if not input_verified:
                success = False
                if not error_message:
                    error_message = "input_effect_not_observed"

                # If input effect is not observed, keep ui_changed result conservative.
                # It may still be true in some apps, but here we prefer traceability.
                if not ui_changed:
                    ui_changed = False

    except Exception as exc:
        new_signature = before_signature
        ui_changed = False
        if not error_message:
            error_message = f"post_action_ui_dump_failed: {type(exc).__name__}: {str(exc)}"

    return make_feedback(
        success=success,
        ui_changed=ui_changed,
        new_signature=new_signature,
        error_message=error_message,
    )


def execute_click(
    device: u2.Device,
    target_id: Optional[str],
    components: list[dict[str, Any]],
) -> bool:
    """
    Execute a click action on the target component.
    """
    if target_id is None:
        return False

    component = find_component_by_id(components, target_id)
    if component is None:
        return False

    center = component.get("center", [0, 0])
    if len(center) < 2:
        return False

    x, y = int(center[0]), int(center[1])
    device.click(x, y)
    time.sleep(0.5)
    return True


def execute_input(
    device: u2.Device,
    target_id: Optional[str],
    input_text: str,
    components: list[dict[str, Any]],
) -> bool:
    """
    Execute an input action using a robust multi-strategy fallback chain.

    Strategy order:
    1. Click target field
    2. Try device.send_keys(...)
    3. Try focused element set_text(...)
    4. Try resource-id based set_text(...)
    5. Fallback to adb shell input text
    """
    if target_id is None:
        return False

    component = find_component_by_id(components, target_id)
    if component is None:
        return False

    center = component.get("center", [0, 0])
    if len(center) < 2:
        return False

    x, y = int(center[0]), int(center[1])
    resource_id = normalize_text(component.get("resource_id"))

    # Step 1: focus the target field
    device.click(x, y)
    time.sleep(0.5)

    # Try enabling fast input IME if available
    try:
        device.set_fastinput_ime(True)
    except Exception:
        pass

    # Strategy 2: direct send_keys
    try:
        try:
            device.clear_text()
            time.sleep(0.2)
        except Exception:
            pass

        device.send_keys(str(input_text), clear=False)
        time.sleep(0.5)
        return True
    except Exception:
        pass

    # Strategy 3: focused node set_text
    try:
        focused_obj = device(focused=True)
        focused_obj.set_text(str(input_text))
        time.sleep(0.5)
        return True
    except Exception:
        pass

    # Strategy 4: resource-id based set_text
    if resource_id:
        try:
            device(resourceId=resource_id).set_text(str(input_text))
            time.sleep(0.5)
            return True
        except Exception:
            pass

    # Strategy 5: adb shell input text fallback
    try:
        escaped_text = escape_android_input_text(str(input_text))
        device.shell(f"input text {escaped_text}")
        time.sleep(0.5)
        return True
    except Exception:
        pass

    return False


def execute_scroll(
    device: u2.Device,
    target_id: Optional[str],
    components: list[dict[str, Any]],
) -> bool:
    """
    Execute a vertical upward scroll within the target component area.

    Strategy:
    - If target component exists, scroll inside its bounds.
    - Otherwise, fallback to a generic screen swipe.
    """
    component = None
    if target_id is not None:
        component = find_component_by_id(components, target_id)

    if component is not None:
        bounds = component.get("bounds", [0, 0, 0, 0])
        if is_valid_bounds(bounds):
            x1, y1, x2, y2 = bounds
            center_x = (x1 + x2) // 2

            start_y = int(y2 - max(80, (y2 - y1) * 0.2))
            end_y = int(y1 + max(80, (y2 - y1) * 0.2))

            if start_y > end_y:
                device.swipe(center_x, start_y, center_x, end_y, 0.2)
                return True

    width, height = device.window_size()
    center_x = width // 2
    start_y = int(height * 0.75)
    end_y = int(height * 0.35)

    device.swipe(center_x, start_y, center_x, end_y, 0.2)
    return True


def detect_ui_changed(
    before_components: list[dict[str, Any]],
    after_components: list[dict[str, Any]],
    before_signature: str,
    after_signature: str,
    local_action: dict[str, Any],
) -> bool:
    """
    Detect whether the UI meaningfully changed after the action.

    For input actions, direct signature comparison may be insufficient,
    so additional text-based checks are used.
    """
    if before_signature != after_signature:
        return True

    action_type = local_action.get("action_type")
    target_id = local_action.get("target_id")
    input_text = normalize_text(local_action.get("input_text"))

    if action_type == "input":
        if input_text and contains_text_in_components(after_components, input_text):
            return True

        before_target = find_component_by_id(before_components, target_id) if target_id else None
        after_target = find_component_by_id(after_components, target_id) if target_id else None

        if before_target is not None and after_target is not None:
            before_text = normalize_text(before_target.get("text"))
            after_text = normalize_text(after_target.get("text"))
            if before_text != after_text:
                return True

            before_desc = normalize_text(before_target.get("content_desc"))
            after_desc = normalize_text(after_target.get("content_desc"))
            if before_desc != after_desc:
                return True

    if action_type == "click":
        before_target = find_component_by_id(before_components, target_id) if target_id else None
        after_target = find_component_by_id(after_components, target_id) if target_id else None

        if before_target is not None and after_target is not None:
            if before_target.get("selected") != after_target.get("selected"):
                return True
            if before_target.get("checked") != after_target.get("checked"):
                return True

    return False


def verify_input_effect(
    before_components: list[dict[str, Any]],
    after_components: list[dict[str, Any]],
    local_action: dict[str, Any],
) -> bool:
    """
    Verify whether the input action likely took effect.

    Verification strategies:
    1. input_text appears in the new component texts
    2. target component text/content changes
    """
    input_text = normalize_text(local_action.get("input_text"))
    target_id = local_action.get("target_id")

    if input_text and contains_text_in_components(after_components, input_text):
        return True

    if target_id is not None:
        before_target = find_component_by_id(before_components, target_id)
        after_target = find_component_by_id(after_components, target_id)

        if before_target is not None and after_target is not None:
            before_text = normalize_text(before_target.get("text"))
            after_text = normalize_text(after_target.get("text"))
            if before_text != after_text:
                return True

            before_desc = normalize_text(before_target.get("content_desc"))
            after_desc = normalize_text(after_target.get("content_desc"))
            if before_desc != after_desc:
                return True

    return False


def contains_text_in_components(
    components: list[dict[str, Any]],
    target_text: str,
) -> bool:
    """
    Check whether target_text appears in any component text or content description.
    """
    target_text = normalize_text(target_text)
    if target_text == "":
        return False

    for component in components:
        text = normalize_text(component.get("text"))
        content_desc = normalize_text(component.get("content_desc"))

        if target_text in text:
            return True
        if target_text in content_desc:
            return True

    return False


def find_component_by_id(
    components: list[dict[str, Any]],
    target_id: Optional[str],
) -> Optional[dict[str, Any]]:
    """
    Find a component in the component list by its id.
    """
    if target_id is None:
        return None

    for component in components:
        if component.get("id") == target_id:
            return deepcopy(component)
    return None


def is_valid_bounds(bounds: Any) -> bool:
    """
    Check whether bounds are valid and usable.
    """
    if not isinstance(bounds, list) or len(bounds) != 4:
        return False

    x1, y1, x2, y2 = bounds

    if not all(isinstance(v, int) for v in bounds):
        return False

    if x2 <= x1 or y2 <= y1:
        return False

    return True


def escape_android_input_text(text: str) -> str:
    """
    Escape text for 'adb shell input text'.

    This function is intentionally conservative and targets common cases.
    """
    escaped = text.replace(" ", "%s")
    escaped = escaped.replace("&", r"\&")
    escaped = escaped.replace("|", r"\|")
    escaped = escaped.replace("<", r"\<")
    escaped = escaped.replace(">", r"\>")
    escaped = escaped.replace("(", r"\(")
    escaped = escaped.replace(")", r"\)")
    escaped = escaped.replace(";", r"\;")
    return escaped


def normalize_text(value: Any) -> str:
    """
    Normalize string-like values.
    """
    if value is None:
        return ""
    return str(value).strip()


def make_feedback(
    success: bool,
    ui_changed: bool,
    new_signature: str,
    error_message: str,
) -> dict[str, Any]:
    """
    Construct an ExecutionFeedback object.
    """
    return {
        "success": success,
        "ui_changed": ui_changed,
        "new_signature": new_signature,
        "error_message": error_message,
    }


def export_execution_feedback(feedback: dict[str, Any]) -> dict[str, Any]:
    """
    Return a safe exported copy of the ExecutionFeedback.
    """
    return deepcopy(feedback)