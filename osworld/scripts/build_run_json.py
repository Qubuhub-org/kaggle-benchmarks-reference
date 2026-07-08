"""Fetches model proxy logs and builds a task.run.json matching the benchmark schema."""

import csv
import io
import json
import os
import re
import sys
import uuid
from pathlib import Path
from urllib.request import Request, urlopen

RESULTS_ROOT = Path(os.environ.get("OSWORLD_FINAL_RESULTS_PATH", "/kaggle/working"))
TRACES_DIR = RESULTS_ROOT / "model_traces"
OUTPUT_PATH = RESULTS_ROOT / "task.run.json"
OSWORLD_DIR = Path("/tmp/OSWorld")
TASK_OUTPUT_LOG = Path("/tmp/osworld_output.txt")
RESULT_FILE = RESULTS_ROOT / "result.txt"
TASK_METADATA_PATH = Path(__file__).parent / "task_metadata.json"


def api_get(path):
    """Make an authenticated GET request to the model proxy."""
    base_url = os.path.dirname(os.environ["MODEL_PROXY_URL"])
    url = base_url.rstrip("/") + path
    req = Request(url, headers={
        "Authorization": f"Bearer {os.environ['MODEL_PROXY_API_KEY']}",
    })
    with urlopen(req) as resp:
        return resp.read().decode()


def fetch_logs():
    """Fetch the logs list and each individual log entry."""
    TRACES_DIR.mkdir(parents=True, exist_ok=True)

    csv_text = api_get("/logs/list")
    csv_path = TRACES_DIR / "logs_list.csv"
    csv_path.write_text(csv_text)

    reader = csv.DictReader(io.StringIO(csv_text))
    entries = list(reader)
    print(f"Found {len(entries)} log entries")

    # CSV is newest-first, reverse for chronological order
    for i, row in enumerate(reversed(entries)):
        key = row["key"]
        log_text = api_get(f"/logs/lookup/{key}")
        log_path = TRACES_DIR / f"{i}_{key}.log"
        log_path.write_text(log_text)
        print(f"Fetched log: {i}_{key}")

    return entries


def load_task_metadata():
    """Load the OSWorld task JSON for this task's domain and ID."""
    domain = os.environ.get("OSWORLD_TASK_DOMAIN", "")
    task_id = os.environ.get("OSWORLD_TASK_ID", "")
    task_path = OSWORLD_DIR / "evaluation_examples" / "examples" / domain / f"{task_id}.json"
    if task_path.exists():
        with open(task_path) as f:
            return json.load(f)
    return None


def detect_error():
    """Check if the task errored by inspecting exit code and output log."""
    exit_code = int(os.environ.get("TASK_EXIT_CODE", "0"))
    if exit_code != 0:
        # Try to extract a meaningful error message from the output log
        error_msg = f"Task exited with code {exit_code}"
        if TASK_OUTPUT_LOG.exists():
            lines = TASK_OUTPUT_LOG.read_text().strip().splitlines()
            # Look for traceback or error lines near the end
            error_lines = []
            in_traceback = False
            for line in lines:
                if "Traceback" in line:
                    in_traceback = True
                if in_traceback:
                    error_lines.append(line)
            if error_lines:
                error_msg = "\n".join(error_lines[-20:])
            elif lines:
                error_msg = "\n".join(lines[-10:])
        return error_msg
    return None


def load_result():
    """Read result.txt and return the boolean result.

    The file contains a float (e.g. 1.0 or 0.0) since OSWorld averages
    results across tasks, but we only run one task at a time.
    """
    if RESULT_FILE.exists():
        value = RESULT_FILE.read_text().strip()
        try:
            return float(value) > 0
        except ValueError:
            return None
    return None


def build_assertion(task_meta, bool_result, conversation_id, last_request_id):
    """Build an assertion from OSWorld evaluator metadata and result."""
    if task_meta is None or bool_result is None:
        return None

    evaluator = task_meta.get("evaluator")
    if not evaluator:
        return None

    # Build a human-readable description of the result source
    result_cfg = evaluator.get("result", {})
    if isinstance(result_cfg, list):
        result_cfg = result_cfg[0]  # use first for display
    result_type = result_cfg.get("type", "") if isinstance(result_cfg, dict) else ""
    result_command = result_cfg.get("command", "") if isinstance(result_cfg, dict) else ""
    result_path = result_cfg.get("path", "") if isinstance(result_cfg, dict) else ""

    # Build result source string (e.g. "vm_command_line: which spotify")
    if result_command:
        if isinstance(result_command, list):
            result_source = " ".join(result_command)
        else:
            result_source = result_command
    elif result_path:
        result_source = result_path
    elif result_type:
        result_source = result_type
    else:
        result_source = ""

    # Build evaluator function string
    func = evaluator.get("func", "unknown")
    if isinstance(func, list):
        conj = evaluator.get("conj", "and")
        func_str = f" {conj} ".join(func)
    else:
        func_str = func

    # Build expectation string from the expected field
    expected = evaluator.get("expected", {})
    if isinstance(expected, dict):
        rules = expected.get("rules", {})
        if isinstance(rules, dict):
            parts = []
            if rules.get("include"):
                parts.append(f"include: {rules['include']}")
            if rules.get("exclude"):
                parts.append(f"exclude: {rules['exclude']}")
            if rules.get("expected"):
                parts.append(f"expected: {rules['expected']}")
            if rules.get("type"):
                parts.append(f"type: {rules['type']}")
            expectation = ", ".join(parts) if parts else json.dumps(expected)
        else:
            expectation = json.dumps(expected)
    elif isinstance(expected, list):
        expectation = json.dumps(expected)
    else:
        expectation = str(expected)

    status = (
        "BENCHMARK_TASK_RUN_ASSERTION_STATUS_PASSED" if bool_result
        else "BENCHMARK_TASK_RUN_ASSERTION_STATUS_FAILED"
    )

    # Definition: "result_source | func(expectation)"
    if result_source:
        definition = f"{result_source} | {func_str}({expectation})"
    else:
        definition = f"{func_str}({expectation})"

    assertion = {
        "definition": definition,
        "expectation": expectation,
        "status": status,
    }

    if last_request_id:
        assertion["conversationRequestIds"] = [{
            "conversationId": conversation_id,
            "requestId": last_request_id,
        }]

    return assertion


def parse_log_sections(log_text):
    """Split a log file into named sections delimited by '-- name --' markers."""
    sections = {}
    current = None
    lines = []
    for line in log_text.split("\n"):
        m = re.match(r"^-- (.+?) --$", line)
        if m:
            if current is not None:
                sections[current] = "\n".join(lines)
            current = m.group(1)
            lines = []
        else:
            lines.append(line)
    if current is not None:
        sections[current] = "\n".join(lines)
    return sections


def extract_json_body(http_text):
    """Extract the JSON body from raw HTTP request/response text."""
    parts = http_text.split("\n\n", 1)
    if len(parts) < 2:
        return None
    body = parts[1].strip()
    if not body:
        return None
    try:
        return json.loads(body)
    except json.JSONDecodeError:
        return None


def content_to_parts(content):
    """Convert OpenAI-style message content into a list of proto Part dicts.

    Part is a oneof of text/inline_data/file_data (see benchmark_types.proto),
    so each chunk must be its own Part with exactly one field set.
    """
    if content is None:
        return []
    if isinstance(content, str):
        return [{"text": content}] if content else []
    if not isinstance(content, list):
        return [{"text": str(content)}]

    parts = []
    for item in content:
        if isinstance(item, str):
            if item:
                parts.append({"text": item})
            continue
        if not isinstance(item, dict):
            continue
        item_type = item.get("type")
        if item_type == "text" or (item_type is None and "text" in item):
            text = item.get("text", "")
            if text:
                parts.append({"text": text})
        elif item_type == "image_url":
            url = item.get("image_url", {})
            if isinstance(url, dict):
                url = url.get("url", "")
            if isinstance(url, str) and url.startswith("data:") and "," in url:
                header, data = url.split(",", 1)
                mime = header[5:].split(";")[0] or "application/octet-stream"
                parts.append({"inlineData": {"mimeType": mime, "data": data}})
            elif isinstance(url, str) and url:
                parts.append({"fileData": {"fileUri": url}})
    return parts


def parse_log_file(path):
    """Parse a single log file and return the request messages, response, and metrics."""
    sections = parse_log_sections(path.read_text())

    request_body = extract_json_body(sections.get("request", ""))
    response_body = extract_json_body(sections.get("response", ""))
    if not request_body or not response_body:
        return None

    messages = request_body.get("messages", [])
    last_user_content = None
    for msg in reversed(messages):
        if msg.get("role") == "user":
            last_user_content = msg.get("content", "")
            break

    choices = response_body.get("choices", [])
    assistant_content = ""
    if choices:
        assistant_content = choices[0].get("message", {}).get("content", "")

    usage = response_body.get("usage", {})

    return {
        "model": request_body.get("model", ""),
        "user_parts": content_to_parts(last_user_content),
        "assistant_parts": content_to_parts(assistant_content),
        "input_tokens": usage.get("prompt_tokens", 0),
        "output_tokens": usage.get("completion_tokens", 0),
    }


def load_timestamps(csv_path):
    """Read the logs_list.csv and return (start_time, end_time)."""
    timestamps = []
    with open(csv_path) as f:
        for row in csv.DictReader(f):
            ts = row.get("timestamp", "")
            if ts:
                timestamps.append(ts)
    if not timestamps:
        return None, None
    timestamps.sort()
    return timestamps[0], timestamps[-1]


def build_run_json():
    """Read all fetched log files and produce task.run.json."""
    task_id = os.environ.get("OSWORLD_TASK_ID", "unknown")
    task_domain = os.environ.get("OSWORLD_TASK_DOMAIN", "")

    # Load OSWorld task metadata
    task_meta = load_task_metadata()
    task_definition = json.dumps(task_meta, indent=2) if task_meta else None

    # Use curated task name/description from mapping, fall back to raw values
    task_mapping = {}
    if TASK_METADATA_PATH.exists():
        with open(TASK_METADATA_PATH) as f:
            task_mapping = json.load(f)
    mapped = task_mapping.get(task_domain, {}).get(task_id, {})
    task_name = mapped.get("name", f"{task_domain}/{task_id}")
    task_description = mapped.get("description")
    if not task_description and task_meta:
        task_description = task_meta.get("instruction", "")[:255]

    # Detect errors
    error_msg = detect_error()

    # Determine state
    if error_msg:
        state = "BENCHMARK_TASK_RUN_STATE_ERRORED"
    else:
        state = "BENCHMARK_TASK_RUN_STATE_COMPLETED"

    # Load result
    bool_result = load_result()

    # Timestamps
    csv_path = TRACES_DIR / "logs_list.csv"
    start_time, end_time = None, None
    if csv_path.exists():
        start_time, end_time = load_timestamps(csv_path)

    # Parse log files
    log_files = sorted(TRACES_DIR.glob("*.log"), key=lambda p: int(p.stem.split("_")[0]))

    # IDs: use taskVersion.name + short random hash (matches kaggle-benchmarks SDK)
    short_hash = uuid.uuid4().hex[:8]
    conversation_id = f"{task_name}-{short_hash}"
    py_run_id = f"{conversation_id}-Run #1"

    requests = []
    model_slug = None
    total_input = 0
    total_output = 0

    for i, log_file in enumerate(log_files):
        parsed = parse_log_file(log_file)
        if parsed is None:
            continue

        if model_slug is None:
            model_slug = parsed["model"]

        contents = []
        if parsed["user_parts"]:
            contents.append({
                "parts": parsed["user_parts"],
                "role": "CONTENT_ROLE_USER",
                "senderName": "User",
            })
        if parsed["assistant_parts"]:
            contents.append({
                "parts": parsed["assistant_parts"],
                "role": "CONTENT_ROLE_ASSISTANT",
                "senderName": parsed["model"],
            })

        total_input += parsed["input_tokens"]
        total_output += parsed["output_tokens"]

        requests.append({
            "contents": contents,
            "metrics": {
                "inputTokens": parsed["input_tokens"],
                "outputTokens": parsed["output_tokens"],
            },
            "id": f"{conversation_id}-req-{i + 1}",
        })

    # Build assertion from evaluator metadata
    last_req_id = requests[-1]["id"] if requests else None
    assertion = build_assertion(task_meta, bool_result, conversation_id, last_req_id)
    assertions = [assertion] if assertion else []

    # Build task version
    task_version = {"name": task_name}
    if task_description:
        task_version["description"] = task_description
    if task_definition:
        task_version["definition"] = task_definition

    # Build run JSON
    run_json = {
        "taskVersion": task_version,
        "modelVersion": {
            "slug": model_slug or os.environ.get("LLM_DEFAULT", ""),
        },
        "state": state,
        "startTime": start_time,
        "endTime": end_time,
        "conversations": [
            {
                "id": conversation_id,
                "requests": requests,
                "metrics": {
                    "inputTokens": total_input,
                    "outputTokens": total_output,
                },
            }
        ],
        "results": [],
        "assertions": assertions,
        "pyRunId": py_run_id,
    }

    if error_msg:
        run_json["errorMessage"] = error_msg

    if bool_result is not None:
        run_json["results"] = [
            {"type": "AGGREGATED", "booleanResult": bool_result}
        ]

    with open(OUTPUT_PATH, "w") as f:
        json.dump(run_json, f, indent=4)

    status = "PASSED" if bool_result else ("ERRORED" if error_msg else "FAILED")
    print(f"Wrote task.run.json: {status}, {len(requests)} requests ({total_input} in / {total_output} out tokens)")


def main():
    fetch_logs()
    build_run_json()


if __name__ == "__main__":
    main()
