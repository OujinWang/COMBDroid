from __future__ import annotations

import json
import os
import re
import xml.etree.ElementTree as ET
from typing import Any, Optional

import uiautomator2 as u2


SYSTEM_PACKAGES = {
    "com.android.systemui",
}


def parse_bounds(bounds_str: str) -> list[int]:
    """
    Parse Android bounds string.

    Example:
        "[0,72][1080,2400]" -> [0, 72, 1080, 2400]
    """
    if not bounds_str:
        return [0, 0, 0, 0]

    nums = re.findall(r"\d+", bounds_str)
    if len(nums) != 4:
        return [0, 0, 0, 0]

    return [int(x) for x in nums]


def compute_center(bounds: list[int]) -> list[int]:
    x1, y1, x2, y2 = bounds
    return [(x1 + x2) // 2, (y1 + y2) // 2]


def compute_area(bounds: list[int]) -> int:
    x1, y1, x2, y2 = bounds
    width = max(0, x2 - x1)
    height = max(0, y2 - y1)
    return width * height


def str_to_bool(value: Optional[str]) -> bool:
    return str(value).lower() == "true"


def get_screen_size_from_device(device: u2.Device) -> tuple[int, int]:
    """
    Return (width, height) of the current device screen.
    """
    width, height = device.window_size()
    return int(width), int(height)


def is_in_screen(bounds: list[int], screen_width: int, screen_height: int) -> bool:
    """
    Check whether the component is at least partially inside the screen.
    """
    x1, y1, x2, y2 = bounds

    if x2 <= 0 or y2 <= 0:
        return False
    if x1 >= screen_width or y1 >= screen_height:
        return False
    if x2 <= x1 or y2 <= y1:
        return False

    return True


def infer_visible(
    node_attrib: dict[str, str],
    bounds: list[int],
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None,
) -> bool:
    """
    Infer visibility of a component.
    """
    if "visible-to-user" in node_attrib:
        visible_to_user = str_to_bool(node_attrib.get("visible-to-user"))
        if not visible_to_user:
            return False

    area = compute_area(bounds)
    if area <= 0:
        return False

    if screen_width is not None and screen_height is not None:
        return is_in_screen(bounds, screen_width, screen_height)

    return True


def map_widget_type(class_name: str, clickable: bool, scrollable: bool) -> str:
    """
    Map raw Android widget class to a semantic widget type.
    """
    if not class_name:
        if scrollable:
            return "ScrollContainer"
        if clickable:
            return "Clickable"
        return "Other"

    class_name_lower = class_name.lower()

    if "edittext" in class_name_lower:
        return "Input"

    if "button" in class_name_lower or "imagebutton" in class_name_lower:
        return "Button"

    if "spinner" in class_name_lower:
        return "Dropdown"

    if "checkbox" in class_name_lower or "radiobutton" in class_name_lower:
        return "Selection"

    if "switch" in class_name_lower or "togglebutton" in class_name_lower:
        return "Selection"

    if (
        "scrollview" in class_name_lower
        or "recyclerview" in class_name_lower
        or "listview" in class_name_lower
        or "viewpager" in class_name_lower
    ):
        return "ScrollContainer"

    if "textview" in class_name_lower:
        if clickable:
            return "Clickable"
        return "Text"

    if "imageview" in class_name_lower:
        if clickable:
            return "Clickable"
        return "Image"

    if (
        "framelayout" in class_name_lower
        or "linearlayout" in class_name_lower
        or "relativelayout" in class_name_lower
    ):
        if scrollable:
            return "ScrollContainer"
        if clickable:
            return "Clickable"
        return "Container"

    if scrollable:
        return "ScrollContainer"

    if clickable:
        return "Clickable"

    return "Other"


def should_filter_component(
    package_name: str,
    include_system_ui: bool = False,
) -> bool:
    """
    Decide whether a component should be filtered out.
    """
    if include_system_ui:
        return False

    return package_name in SYSTEM_PACKAGES


def dump_ui_state(
    device: u2.Device,
    output_dir: str = "tmp",
    screenshot_name: str = "screen.png",
    xml_name: str = "hierarchy.xml",
    include_system_ui: bool = False,
    export_debug_json: bool = True,
    ui_state_json_name: str = "ui_state.json",
    actionable_json_name: str = "actionable_components.json",
) -> dict[str, Any]:
    """
    Dump current UI state and return a structured UIState object.
    """
    os.makedirs(output_dir, exist_ok=True)

    screenshot_path = os.path.join(output_dir, screenshot_name)
    xml_path = os.path.join(output_dir, xml_name)

    device.screenshot(screenshot_path)

    raw_xml = device.dump_hierarchy()
    with open(xml_path, "w", encoding="utf-8") as f:
        f.write(raw_xml)

    screen_width, screen_height = get_screen_size_from_device(device)

    components = extract_components_from_xml(
        xml_str=raw_xml,
        screen_width=screen_width,
        screen_height=screen_height,
        include_system_ui=include_system_ui,
    )

    ui_state = {
        "screenshot_path": screenshot_path,
        "xml_path": xml_path,
        "raw_xml": raw_xml,
        "components": components,
    }

    if export_debug_json:
        export_ui_state_json(
            ui_state,
            output_dir=output_dir,
            file_name=ui_state_json_name,
        )
        export_actionable_components_json(
            components=ui_state["components"],
            output_dir=output_dir,
            file_name=actionable_json_name,
        )

    return ui_state


def extract_components_from_xml(
    xml_str: str,
    screen_width: Optional[int] = None,
    screen_height: Optional[int] = None,
    include_system_ui: bool = False,
) -> list[dict[str, Any]]:
    """
    Parse XML hierarchy into a list of Component objects.
    """
    root = ET.fromstring(xml_str)

    components: list[dict[str, Any]] = []
    node_id_to_children: dict[str, list[str]] = {}

    node_counter = 0

    def dfs(
        node: ET.Element,
        parent_id: Optional[str],
        depth: int,
        in_scroll_container: bool,
    ) -> None:
        nonlocal node_counter

        if node.tag != "node":
            for child in list(node):
                dfs(child, parent_id, depth, in_scroll_container)
            return

        package_name = node.attrib.get("package", "") or ""

        filtered = should_filter_component(
            package_name=package_name,
            include_system_ui=include_system_ui,
        )

        current_node_id = f"node_{node_counter}"
        node_counter += 1

        class_name = node.attrib.get("class", "") or ""
        text = node.attrib.get("text", "") or ""
        resource_id = node.attrib.get("resource-id", "") or ""
        content_desc = node.attrib.get("content-desc", "") or ""
        bounds = parse_bounds(node.attrib.get("bounds", ""))

        clickable = str_to_bool(node.attrib.get("clickable"))
        scrollable = str_to_bool(node.attrib.get("scrollable"))
        enabled = str_to_bool(node.attrib.get("enabled"))
        checked = str_to_bool(node.attrib.get("checked"))
        selected = str_to_bool(node.attrib.get("selected"))

        current_in_scroll = in_scroll_container or scrollable

        component_type = map_widget_type(
            class_name=class_name,
            clickable=clickable,
            scrollable=scrollable,
        )

        center = compute_center(bounds)
        area = compute_area(bounds)
        visible = infer_visible(
            node_attrib=node.attrib,
            bounds=bounds,
            screen_width=screen_width,
            screen_height=screen_height,
        )

        component = {
            "id": current_node_id,
            "type": component_type,
            "class_name": class_name,
            "text": text,
            "resource_id": resource_id,
            "content_desc": content_desc,
            "bounds": bounds,
            "center": center,
            "area": area,
            "visible": visible,
            "clickable": clickable,
            "scrollable": scrollable,
            "enabled": enabled,
            "checked": checked,
            "selected": selected,
            "parent_id": parent_id,
            "children_ids": [],
            "depth": depth,
            "in_scroll_container": current_in_scroll,
            "package_name": package_name,
        }

        if not filtered:
            components.append(component)
            node_id_to_children[current_node_id] = []

            if parent_id is not None and parent_id in node_id_to_children:
                node_id_to_children[parent_id].append(current_node_id)

            next_parent_id = current_node_id
        else:
            next_parent_id = parent_id

        for child in list(node):
            dfs(
                node=child,
                parent_id=next_parent_id,
                depth=depth + 1,
                in_scroll_container=current_in_scroll,
            )

    dfs(
        node=root,
        parent_id=None,
        depth=0,
        in_scroll_container=False,
    )

    component_index = {component["id"]: component for component in components}
    for node_id, children_ids in node_id_to_children.items():
        if node_id in component_index:
            component_index[node_id]["children_ids"] = children_ids

    return components


def build_state_signature(
    components: list[dict[str, Any]],
    max_items: int = 50,
) -> str:
    """
    Build a lightweight UI signature for repeated-page detection.
    """
    tokens: list[str] = []

    for component in components[:max_items]:
        token = "|".join(
            [
                str(component.get("type", "")),
                str(component.get("text", ""))[:30],
                str(component.get("resource_id", ""))[:50],
                str(component.get("visible", False)),
            ]
        )
        tokens.append(token)

    return "||".join(tokens)


def filter_actionable_components(components: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """
    Return a list of components that are potentially actionable.
    """
    actionable: list[dict[str, Any]] = []

    actionable_types = {
        "Input",
        "Button",
        "Dropdown",
        "Selection",
        "ScrollContainer",
        "Clickable",
    }

    for component in components:
        if component.get("type") in actionable_types:
            actionable.append(component)
            continue

        if component.get("clickable", False):
            actionable.append(component)
            continue

        if component.get("scrollable", False):
            actionable.append(component)
            continue

    return actionable


def export_ui_state_json(
    ui_state: dict[str, Any],
    output_dir: str = "tmp",
    file_name: str = "ui_state.json",
) -> None:
    """
    Export UIState to JSON for debugging and inspection.
    """
    export_data = {
        "screenshot_path": ui_state.get("screenshot_path"),
        "xml_path": ui_state.get("xml_path"),
        "component_count": len(ui_state.get("components", [])),
        "components": ui_state.get("components", []),
    }

    file_path = os.path.join(output_dir, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)


def export_actionable_components_json(
    components: list[dict[str, Any]],
    output_dir: str = "tmp",
    file_name: str = "actionable_components.json",
) -> None:
    """
    Export actionable components to JSON.
    """
    actionable = filter_actionable_components(components)
    export_data = {
        "actionable_component_count": len(actionable),
        "actionable_components": actionable,
    }

    file_path = os.path.join(output_dir, file_name)
    with open(file_path, "w", encoding="utf-8") as f:
        json.dump(export_data, f, ensure_ascii=False, indent=2)


def connect_device(device_serial: Optional[str] = None) -> u2.Device:
    """
    Connect to an Android device.
    """
    if device_serial is not None:
        return u2.connect(device_serial)
    return u2.connect()


def collect_current_ui_state(
    device: u2.Device,
    output_dir: str = "tmp",
    include_system_ui: bool = False,
    screenshot_name: str = "screen.png",
    xml_name: str = "hierarchy.xml",
    ui_state_json_name: str = "ui_state.json",
    actionable_json_name: str = "actionable_components.json",
) -> dict[str, Any]:
    """
    High-level helper to collect UIState and export debug JSON files.
    """
    return dump_ui_state(
        device=device,
        output_dir=output_dir,
        screenshot_name=screenshot_name,
        xml_name=xml_name,
        include_system_ui=include_system_ui,
        export_debug_json=True,
        ui_state_json_name=ui_state_json_name,
        actionable_json_name=actionable_json_name,
    )