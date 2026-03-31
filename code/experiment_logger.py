from __future__ import annotations

import os
from pathlib import Path


class ExperimentLogger:
    """
    Simple experiment logger.

    Directory structure:

    runs/
        run_name/
            step_000/
            step_001/
            ...
    """

    def __init__(
        self,
        base_dir: str = "runs",
        run_name: str | None = None,
    ):
        self.base_dir = base_dir

        if run_name is None:
            run_name = "default_run"

        self.run_name = run_name
        self.run_dir = os.path.join(base_dir, run_name)

        Path(self.run_dir).mkdir(parents=True, exist_ok=True)

    def get_run_dir(self) -> str:
        return self.run_dir

    def get_step_dir(self, step_index: int) -> str:
        step_dir = os.path.join(self.run_dir, f"step_{step_index:03d}")
        Path(step_dir).mkdir(parents=True, exist_ok=True)
        return step_dir

    def get_prompt_package_path(self, step_index: int) -> str:
        step_dir = self.get_step_dir(step_index)
        return os.path.join(step_dir, "prompt_package.json")

    def get_system_prompt_path(self, step_index: int) -> str:
        step_dir = self.get_step_dir(step_index)
        return os.path.join(step_dir, "system_prompt.txt")

    def get_user_prompt_path(self, step_index: int) -> str:
        step_dir = self.get_step_dir(step_index)
        return os.path.join(step_dir, "user_prompt.txt")

    def get_llm_response_path(self, step_index: int) -> str:
        step_dir = self.get_step_dir(step_index)
        return os.path.join(step_dir, "llm_response.json")

    def get_step_result_path(self, step_index: int) -> str:
        step_dir = self.get_step_dir(step_index)
        return os.path.join(step_dir, "step_result.json")

    def get_memory_snapshot_path(self, step_index: int) -> str:
        step_dir = self.get_step_dir(step_index)
        return os.path.join(step_dir, "memory_snapshot.json")

    def get_run_summary_path(self) -> str:
        return os.path.join(self.run_dir, "run_summary.json")