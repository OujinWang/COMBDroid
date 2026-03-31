from __future__ import annotations

from copy import deepcopy
from typing import Any, Optional


class ContextMemory:
    """
    ContextMemory stores the short-term execution context of the GUI agent.

    It is responsible for:
    - tracking execution steps
    - storing action history
    - storing UI state signatures
    - recording the last action and last feedback
    - detecting repeated UI states
    """

    def __init__(self, max_signature_history: int = 50) -> None:
        self.step_count: int = 0
        self.action_history: list[dict[str, Any]] = []
        self.ui_signatures: list[str] = []
        self.last_action: Optional[dict[str, Any]] = None
        self.last_feedback: Optional[dict[str, Any]] = None
        self.max_signature_history: int = max_signature_history

    def reset(self) -> None:
        """
        Reset the memory to its initial empty state.
        """
        self.step_count = 0
        self.action_history = []
        self.ui_signatures = []
        self.last_action = None
        self.last_feedback = None

    def increment_step(self) -> None:
        """
        Increase the execution step counter by one.
        """
        self.step_count += 1

    def add_action(self, action: dict[str, Any]) -> None:
        """
        Append a new action to the action history and update last_action.
        """
        action_copy = deepcopy(action)
        self.action_history.append(action_copy)
        self.last_action = action_copy

    def add_ui_signature(self, signature: str) -> None:
        """
        Append a UI signature to the signature history.

        If the history exceeds max_signature_history, discard the oldest one.
        """
        self.ui_signatures.append(signature)

        if len(self.ui_signatures) > self.max_signature_history:
            self.ui_signatures.pop(0)

    def update_feedback(self, feedback: dict[str, Any]) -> None:
        """
        Update the last execution feedback.
        """
        self.last_feedback = deepcopy(feedback)

    def has_seen_signature(self, signature: str) -> bool:
        """
        Return True if the signature has already appeared in the memory.
        """
        return signature in self.ui_signatures

    def count_signature_occurrences(self, signature: str) -> int:
        """
        Count how many times a signature appears in the signature history.
        """
        return self.ui_signatures.count(signature)

    def is_repeated_state(self, signature: str, repeat_threshold: int = 2) -> bool:
        """
        Determine whether a state is repeated too many times.

        Example:
        - repeat_threshold = 2
        - if a signature already appeared 2 times or more, return True
        """
        return self.count_signature_occurrences(signature) >= repeat_threshold

    def get_recent_actions(self, k: int = 5) -> list[dict[str, Any]]:
        """
        Return the most recent k actions.
        """
        if k <= 0:
            return []

        return deepcopy(self.action_history[-k:])

    def get_last_signature(self) -> Optional[str]:
        """
        Return the latest UI signature if available.
        """
        if not self.ui_signatures:
            return None
        return self.ui_signatures[-1]

    def get_previous_signature(self) -> Optional[str]:
        """
        Return the second latest UI signature if available.
        """
        if len(self.ui_signatures) < 2:
            return None
        return self.ui_signatures[-2]

    def did_ui_change(self) -> Optional[bool]:
        """
        Compare the latest two signatures and determine whether the UI changed.

        Returns:
        - True: UI changed
        - False: UI did not change
        - None: insufficient history
        """
        current_signature = self.get_last_signature()
        previous_signature = self.get_previous_signature()

        if current_signature is None or previous_signature is None:
            return None

        return current_signature != previous_signature

    def get_action_count(self) -> int:
        """
        Return the total number of recorded actions.
        """
        return len(self.action_history)

    def get_signature_count(self) -> int:
        """
        Return the total number of recorded UI signatures.
        """
        return len(self.ui_signatures)

    def export(self) -> dict[str, Any]:
        """
        Export the current memory state as a structured dictionary.

        Exported schema:
        {
            "step_count": int,
            "action_history": list[LocalAction],
            "ui_signatures": list[str],
            "last_action": LocalAction | None,
            "last_feedback": ExecutionFeedback | None
        }
        """
        return {
            "step_count": self.step_count,
            "action_history": deepcopy(self.action_history),
            "ui_signatures": deepcopy(self.ui_signatures),
            "last_action": deepcopy(self.last_action),
            "last_feedback": deepcopy(self.last_feedback),
        }

    def load(self, memory_data: dict[str, Any]) -> None:
        """
        Load memory state from a dictionary.
        """
        self.step_count = int(memory_data.get("step_count", 0))
        self.action_history = deepcopy(memory_data.get("action_history", []))
        self.ui_signatures = deepcopy(memory_data.get("ui_signatures", []))
        self.last_action = deepcopy(memory_data.get("last_action"))
        self.last_feedback = deepcopy(memory_data.get("last_feedback"))

    def update(
        self,
        action: Optional[dict[str, Any]] = None,
        signature: Optional[str] = None,
        feedback: Optional[dict[str, Any]] = None,
        increment_step: bool = True,
    ) -> None:
        """
        Unified update interface for one execution round.

        Typical use:
        - add action
        - add current UI signature
        - add execution feedback
        - increment step count

        Parameters:
        - action: current LocalAction
        - signature: current UI signature
        - feedback: current ExecutionFeedback
        - increment_step: whether to increment step_count
        """
        if increment_step:
            self.increment_step()

        if action is not None:
            self.add_action(action)

        if signature is not None:
            self.add_ui_signature(signature)

        if feedback is not None:
            self.update_feedback(feedback)