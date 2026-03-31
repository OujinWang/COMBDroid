from __future__ import annotations

import json
import os
import time
from copy import deepcopy
from typing import Any, Optional

import uiautomator2 as u2

from action.executor import execute_action
from action.local_action import build_local_action_from_llm_response_file
from experiment_logger import ExperimentLogger
from memory.context_memory import ContextMemory
from perception.extract_components import (
    build_state_signature,
    collect_current_ui_state,
)
from planning.global_plan import build_gpt_prompt_package


class GUIAgentController:
    """
    Main controller for the manual GPT-driven GUI Agent Loop.
    """

    def __init__(
        self,
        device: u2.Device,
        output_dir: str = "runs",
        run_name: str | None = None,
        max_steps: int = 10,
        include_system_ui: bool = False,
        repeat_threshold: int = 2,
        export_step_logs: bool = True,
        wait_for_llm_response: bool = True,
        llm_poll_interval: float = 1.0,
        llm_wait_timeout: float = 600.0,
    ) -> None:
        self.device = device
        self.max_steps = max_steps
        self.include_system_ui = include_system_ui
        self.repeat_threshold = repeat_threshold
        self.export_step_logs = export_step_logs
        self.wait_for_llm_response = wait_for_llm_response
        self.llm_poll_interval = llm_poll_interval
        self.llm_wait_timeout = llm_wait_timeout

        self.memory = ContextMemory()

        # Repeated-state monitor:
        # only count repeated failures when the same post-action signature
        # and the same action key appear consecutively.
        self.no_change_counter = 0
        self.last_no_change_signature: Optional[str] = None
        self.last_no_change_action_key: Optional[tuple[Any, ...]] = None

        self.logger = ExperimentLogger(base_dir=output_dir, run_name=run_name)
        self.output_dir = self.logger.get_run_dir()

    def run(self) -> dict[str, Any]:
        """
        Run the manual GPT-driven GUI Agent Loop.
        """
        run_summary = {
            "terminated": False,
            "termination_reason": "",
            "executed_steps": 0,
            "memory": {},
            "run_dir": self.output_dir,
        }

        for step_index in range(self.max_steps):
            step_result = self.run_single_step(step_index=step_index)
            run_summary["executed_steps"] = step_index + 1

            if self.export_step_logs:
                self.export_step_result(step_index=step_index, step_result=step_result)

            termination_reason = self.check_termination(step_result=step_result)

            if termination_reason is not None:
                run_summary["terminated"] = True
                run_summary["termination_reason"] = termination_reason
                break

        if not run_summary["terminated"]:
            run_summary["terminated"] = True
            run_summary["termination_reason"] = "max_steps_reached"

        run_summary["memory"] = self.memory.export()
        self.export_run_summary(run_summary)

        return run_summary

    def run_single_step(self, step_index: int) -> dict[str, Any]:
        """
        Execute a single manual GPT-driven controller step.
        """
        step_dir = self.logger.get_step_dir(step_index)

        ui_state = collect_current_ui_state(
            device=self.device,
            output_dir=step_dir,
            include_system_ui=self.include_system_ui,
            screenshot_name="screen.png",
            xml_name="hierarchy.xml",
            ui_state_json_name="ui_state.json",
            actionable_json_name="actionable_components.json",
        )

        current_signature = build_state_signature(ui_state.get("components", []))

        prompt_package = build_gpt_prompt_package(
            ui_state=ui_state,
            memory=self.memory,
        )

        self.export_prompt_package(step_index=step_index, prompt_package=prompt_package)

        llm_response = self.obtain_llm_response(step_index=step_index)

        local_action = build_local_action_from_llm_response_file(
            llm_response_data=llm_response,
            ui_state=ui_state,
        )

        feedback = execute_action(
            device=self.device,
            local_action=local_action,
            ui_state=ui_state,
            output_dir=step_dir,
        )

        self.memory.update(
            action=local_action,
            signature=current_signature,
            feedback=feedback,
            increment_step=True,
        )

        step_result = {
            "step_index": step_index,
            "step_dir": step_dir,
            "ui_state_meta": self.build_ui_state_meta(ui_state),
            "state_signature": current_signature,
            "post_action_signature": feedback.get("new_signature", ""),
            "prompt_package_meta": self.build_prompt_package_meta(prompt_package),
            "llm_response": deepcopy(llm_response),
            "local_action": deepcopy(local_action),
            "execution_feedback": deepcopy(feedback),
            "memory_snapshot": self.memory.export(),
        }

        return step_result

    def build_ui_state_meta(self, ui_state: dict[str, Any]) -> dict[str, Any]:
        """
        Build a lightweight UIState summary for logging.
        """
        components = ui_state.get("components", [])

        return {
            "screenshot_path": ui_state.get("screenshot_path"),
            "xml_path": ui_state.get("xml_path"),
            "component_count": len(components),
        }

    def build_prompt_package_meta(self, prompt_package: dict[str, Any]) -> dict[str, Any]:
        """
        Build a lightweight prompt package summary for step logging.
        """
        component_brief = prompt_package.get("component_brief", [])
        memory_summary = prompt_package.get("memory_summary", {})

        return {
            "mode": prompt_package.get("mode"),
            "screenshot_path": prompt_package.get("screenshot_path"),
            "component_brief_count": len(component_brief),
            "memory_step_count": memory_summary.get("step_count", 0),
        }

    def export_prompt_package(self, step_index: int, prompt_package: dict[str, Any]) -> None:
        """
        Export prompt package files for manual GPT interaction.
        """
        json_path = self.logger.get_prompt_package_path(step_index)
        system_prompt_path = self.logger.get_system_prompt_path(step_index)
        user_prompt_path = self.logger.get_user_prompt_path(step_index)

        with open(json_path, "w", encoding="utf-8") as f:
            json.dump(prompt_package, f, ensure_ascii=False, indent=2)

        with open(system_prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt_package.get("system_prompt", ""))

        with open(user_prompt_path, "w", encoding="utf-8") as f:
            f.write(prompt_package.get("user_prompt", ""))

    def obtain_llm_response(self, step_index: int) -> dict[str, Any]:
        """
        Obtain LLM response for the current step.
        """
        response_path = self.get_llm_response_path(step_index)

        if not self.wait_for_llm_response:
            if not os.path.exists(response_path):
                raise FileNotFoundError(
                    f"LLM response file not found: {response_path}"
                )
            return self.load_llm_response(response_path)

        start_time = time.time()

        while True:
            if os.path.exists(response_path):
                return self.load_llm_response(response_path)

            elapsed = time.time() - start_time
            if elapsed > self.llm_wait_timeout:
                raise TimeoutError(
                    f"Timed out waiting for LLM response file: {response_path}"
                )

            time.sleep(self.llm_poll_interval)

    def get_llm_response_path(self, step_index: int) -> str:
        """
        Return the expected LLM response file path for the current step.
        """
        return self.logger.get_llm_response_path(step_index)

    def load_llm_response(self, response_path: str) -> dict[str, Any]:
        """
        Load LLM response JSON from file.
        """
        with open(response_path, "r", encoding="utf-8") as f:
            data = json.load(f)

        if not isinstance(data, dict):
            raise ValueError("LLM response JSON must be a dictionary.")

        return data

    def check_termination(self, step_result: dict[str, Any]) -> Optional[str]:
        """
        Check whether the controller should stop.
        """
        local_action = step_result.get("local_action", {})
        feedback = step_result.get("execution_feedback", {})
        action_type = local_action.get("action_type")

        if action_type == "stop":
            return "local_action_stop"

        # Do not count wait toward repeated-state detection.
        if action_type == "wait":
            return None

        ui_changed = feedback.get("ui_changed", False)
        post_action_signature = feedback.get("new_signature", "")

        if ui_changed:
            self.no_change_counter = 0
            self.last_no_change_signature = None
            self.last_no_change_action_key = None
            return None

        action_key = self.build_action_key(local_action)

        # Only terminate if the same ineffective action leads to the same
        # unchanged post-action signature consecutively.
        if (
            self.last_no_change_signature == post_action_signature
            and self.last_no_change_action_key == action_key
        ):
            self.no_change_counter += 1
        else:
            self.no_change_counter = 1
            self.last_no_change_signature = post_action_signature
            self.last_no_change_action_key = action_key

        if self.no_change_counter >= self.repeat_threshold:
            return "repeated_state_detected"

        return None

    def build_action_key(self, local_action: dict[str, Any]) -> tuple[Any, ...]:
        """
        Build a compact action key for repeated-state detection.
        """
        return (
            local_action.get("action_type"),
            local_action.get("target_id"),
            str(local_action.get("input_text", "")).strip(),
        )

    def export_step_result(self, step_index: int, step_result: dict[str, Any]) -> None:
        """
        Export per-step result and memory snapshot.
        """
        result_path = self.logger.get_step_result_path(step_index)
        memory_path = self.logger.get_memory_snapshot_path(step_index)

        with open(result_path, "w", encoding="utf-8") as f:
            json.dump(step_result, f, ensure_ascii=False, indent=2)

        with open(memory_path, "w", encoding="utf-8") as f:
            json.dump(step_result.get("memory_snapshot", {}), f, ensure_ascii=False, indent=2)

    def export_run_summary(self, run_summary: dict[str, Any]) -> None:
        """
        Export the final run summary.
        """
        file_path = self.logger.get_run_summary_path()
        with open(file_path, "w", encoding="utf-8") as f:
            json.dump(run_summary, f, ensure_ascii=False, indent=2)