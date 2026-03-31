from __future__ import annotations

import argparse
from typing import Any

from controller import GUIAgentController
from perception.extract_components import connect_device


def parse_args() -> argparse.Namespace:
    """
    Parse command-line arguments for the GPT-driven GUI Agent entry point.
    """
    parser = argparse.ArgumentParser(
        description="Run the manual GPT-driven GUI Agent Loop on an Android device."
    )

    parser.add_argument(
        "--device",
        type=str,
        required=True,
        help="ADB device serial, e.g. 127.0.0.1:7555 or emulator-5554",
    )

    parser.add_argument(
        "--max-steps",
        type=int,
        default=20,
        help="Maximum number of GUI Agent steps to execute.",
    )

    parser.add_argument(
        "--output-dir",
        type=str,
        default="runs",
        help="Directory for experiment runs.",
    )

    parser.add_argument(
        "--run-name",
        type=str,
        default="",
        help="Optional run name prefix. A timestamp will be appended automatically.",
    )

    parser.add_argument(
        "--include-system-ui",
        action="store_true",
        help="Include system UI components in extracted UIState.",
    )

    parser.add_argument(
        "--repeat-threshold",
        type=int,
        default=2,
        help="Terminate when the same UI signature appears at least this many times.",
    )

    parser.add_argument(
        "--disable-step-logs",
        action="store_true",
        help="Disable exporting per-step JSON logs.",
    )

    parser.add_argument(
        "--llm-poll-interval",
        type=float,
        default=1.0,
        help="Polling interval in seconds while waiting for llm_response.json.",
    )

    parser.add_argument(
        "--llm-wait-timeout",
        type=float,
        default=600.0,
        help="Maximum waiting time in seconds for each LLM response file.",
    )

    parser.add_argument(
        "--no-wait",
        action="store_true",
        help="Do not wait for LLM response files. Fail immediately if the expected file does not exist.",
    )

    return parser.parse_args()


def build_controller(args: argparse.Namespace) -> GUIAgentController:
    """
    Create and configure a GUIAgentController instance.
    """
    device = connect_device(args.device)

    controller = GUIAgentController(
        device=device,
        output_dir=args.output_dir,
        run_name=args.run_name,
        max_steps=args.max_steps,
        include_system_ui=args.include_system_ui,
        repeat_threshold=args.repeat_threshold,
        export_step_logs=not args.disable_step_logs,
        wait_for_llm_response=not args.no_wait,
        llm_poll_interval=args.llm_poll_interval,
        llm_wait_timeout=args.llm_wait_timeout,
    )

    return controller


def main() -> dict[str, Any]:
    """
    Program entry point.
    """
    args = parse_args()
    controller = build_controller(args)
    run_summary = controller.run()
    return run_summary


if __name__ == "__main__":
    main()