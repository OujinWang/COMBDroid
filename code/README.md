# COMBDroid

COMBDroid is a mobile GUI automation framework for handling **combination interactions** in Android apps. It is designed for multi-step GUI tasks that require coordinated operations across multiple widgets within the same functional context, such as booking, search, logging, editing, and configuration flows.

The current implementation follows a modular **Perception → Planning → Action → Execution → Memory** pipeline and supports a manual LLM-driven interaction loop.

---

## Features

- Extracts structured GUI components from Android UI hierarchy
- Captures screenshots for page understanding
- Builds LLM prompts from GUI state and execution memory
- Executes structured GUI actions:
  - `click`
  - `input`
  - `scroll`
  - `wait`
  - `stop`
- Tracks execution feedback and GUI state changes
- Stores step-level artifacts for traceability and debugging
- Maintains context memory across multi-step interactions

---

## Project Structure

```text
GUI_AGENT/
├── action/
│   ├── executor.py
│   └── local_action.py
├── memory/
│   └── context_memory.py
├── perception/
│   └── extract_components.py
├── planning/
│   ├── experience_summarizer.py
│   └── global_plan.py
├── runs/
├── controller.py
├── experiment_logger.py
├── main.py
└── readme.md
```

### Module Overview

* `main.py`
  Entry point for launching the GUI agent.

* `controller.py`
  Controls the full interaction loop, including step execution, termination checks, and logging.

* `experiment_logger.py`
  Manages run directories and step-level output files.

* `perception/extract_components.py`
  Connects to the Android device, captures screenshots, dumps UI hierarchy, and extracts structured GUI components.

* `planning/global_plan.py`
  Builds prompt packages for the planner using the current UI state and memory.

* `planning/experience_summarizer.py`
  Summarizes successful interaction traces into reusable high-level experience memory.

* `action/local_action.py`
  Parses and validates structured LLM responses into executable local actions.

* `action/executor.py`
  Executes actions on the Android device and checks post-action UI changes.

* `memory/context_memory.py`
  Stores recent execution history and interaction context across steps.

---

## Workflow

COMBDroid operates in the following stages:

1. **Perception**

   * Capture the current screenshot
   * Dump the current UI hierarchy
   * Extract GUI components and build a UI state representation

2. **Planning**

   * Construct a prompt package using:

     * current screenshot path
     * component list
     * memory summary
   * Obtain the next action from the LLM

3. **Action Parsing**

   * Convert the LLM response into a validated local action

4. **Execution**

   * Execute the action on the device
   * Re-dump the UI state after execution

5. **Feedback and Memory Update**

   * Check whether the UI changed
   * Record action history and feedback
   * Continue until a termination condition is met

---

## Environment Setup

### 1. Python

Create and activate a Python environment:

```bash
conda create -n combdroid python=3.10 -y
conda activate combdroid
```

Install dependencies:

```bash
pip install -r requirements.txt
```

### 2. Android Testing Environment

COMBDroid requires an Android device environment accessible through **ADB** and compatible with **uiautomator2**.

Before running the framework, ensure that:

* the Android device is visible through `adb devices`
* UI automation is available
* screenshots and UI hierarchy dumping work correctly

---

## Requirements

Dependencies are listed separately in `requirements.txt`.

---

## Running COMBDroid

Basic usage:

```bash
python main.py --device <device_serial> --run-name <run_name>
```

Example:

```bash
python main.py --device <device_serial> --run-name demo_run --max-steps 10
```

### Main Arguments

* `--device`
  Android device serial visible to ADB

* `--run-name`
  Name of the current run

* `--max-steps`
  Maximum number of interaction steps

* `--output-dir`
  Output directory for run artifacts

* `--include-system-ui`
  Include system UI components during perception

* `--repeat-threshold`
  Threshold for repeated ineffective execution

* `--no-wait`
  Do not wait for LLM response files

---

## Manual LLM-Driven Loop

The current implementation supports a manual planning workflow.

At each step, COMBDroid exports:

* prompt package JSON
* system prompt
* user prompt

The expected LLM response is a JSON object containing the next action.

Example action schema:

```json
{
  "page_understanding": "This page is a booking date selection screen.",
  "next_action": {
    "action_type": "click",
    "target_id": "node_42",
    "input_text": "",
    "reason": "Select the check-in date."
  },
  "is_complete": false
}
```

Supported action types:

* `click`
* `input`
* `scroll`
* `wait`
* `stop`

---

## Output Artifacts

Each run produces a structured directory under `runs/`.

Example layout:

```text
runs/
└── <run_name>/
    ├── step_000/
    │   ├── screen.png
    │   ├── hierarchy.xml
    │   ├── ui_state.json
    │   ├── actionable_components.json
    │   ├── prompt_package.json
    │   ├── system_prompt.txt
    │   ├── user_prompt.txt
    │   ├── llm_response.json
    │   ├── step_result.json
    │   └── memory_snapshot.json
    ├── step_001/
    └── ...
```

These artifacts support:

* execution replay
* debugging
* trace analysis
* memory inspection

---

## Current Capabilities

The current codebase supports:

* Android GUI state extraction
* structured component representation
* step-wise LLM planning
* validated local action parsing
* robust input execution with fallbacks
* repeated-state detection
* run logging and memory snapshots

---

## Notes

* Some repository files may be temporary or experiment-specific and are not part of the core runtime pipeline.
* The framework is currently oriented toward Android GUI automation and structured multi-step interaction execution.
* The current implementation is suitable for experimentation, debugging, and extension of LLM-based GUI testing workflows.

---

## Citation

If you use COMBDroid in research, please cite the corresponding paper and repository.
