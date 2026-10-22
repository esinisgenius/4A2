"""Run the agreed Task 1 generation, preserving teacher code and all P0 files."""

from __future__ import annotations

import json
import os
import platform
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

if __package__:
    from .validate_task1 import AEMO_NAME, AEMO_URL, OUTPUT_NAMES, ROOT, digest, validate, validate_aemo
else:
    from validate_task1 import AEMO_NAME, AEMO_URL, OUTPUT_NAMES, ROOT, digest, validate, validate_aemo


def write_report(path: Path, report: dict) -> None:
    temporary = path.with_suffix(".json.tmp")
    temporary.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
    temporary.replace(path)


def main(root: Path = ROOT) -> None:
    output = root / "data/generated"
    cache = output / "aemo_cache" / AEMO_NAME
    docs = root / "docs"
    docs.mkdir(parents=True, exist_ok=True)
    report_path = docs / "task1_run.json"
    preflight_path = docs / "task1_aemo_validation.json"
    validation_path = docs / "task1_validation.json"
    started = datetime.now(timezone.utc).isoformat()
    command = [sys.executable, "vendor/data_generator/generate_dataset.py",
               "--stations", "data/input/stations.csv", "--start", "2026-09-15", "--days", "1",
               "--out", "data/generated", "--seed", "5339", "--sessions-per-connector-day", "3", "2"]
    sources = ["data/input/stations.csv", "data/processed/generator_station_mapping.csv",
               "data/processed/stations_prepared.csv", "data/processed/chargers_prepared.csv",
               "vendor/data_generator/generate_dataset.py"]
    manifest = {
        "started_utc": started, "result": "RUNNING", "stage": "preflight", "validation_result": "NOT_RUN",
        "command": command, "cwd": str(root), "python": platform.python_version(),
        "seed": 5339, "start": "2026-09-15", "days": 1, "sessions_per_connector_day": [3, 2],
        "other_generator_options": "unchanged teacher defaults; dynamic AEMO prices; meter_every=1",
        "text_encoding": "UTF-8 (PYTHONUTF8=1 and PYTHONIOENCODING=utf-8)",
        "aemo_downloaded_by_this_run": not cache.exists(), "aemo_url": AEMO_URL,
    }
    # Invalidate previous results before downloading or examining any inputs.
    write_report(report_path, manifest)
    write_report(preflight_path, {"result": "RUNNING", "started_utc": started})
    write_report(validation_path, {"result": "NOT_RUN", "started_utc": started})
    try:
        cache.parent.mkdir(parents=True, exist_ok=True)
        if not cache.exists():
            request = urllib.request.Request(AEMO_URL, headers={"User-Agent": "Mozilla/5.0"})
            with urllib.request.urlopen(request, timeout=60) as response:
                raw = response.read()
            cache.write_bytes(raw)
        preflight, _ = validate_aemo(cache)
        write_report(preflight_path, {**preflight, "started_utc": started})
        print(f"AEMO preflight PASS: {preflight['intervals']} five-minute intervals", flush=True)

        manifest["stage"] = "generation"
        write_report(report_path, manifest)
        before = {name: digest(root / name) for name in sources}
        manifest.update(aemo_sha256=digest(cache), input_sha256=before)
        environment = os.environ.copy()
        environment["PYTHONUTF8"] = "1"
        environment["PYTHONIOENCODING"] = "utf-8"
        completed = subprocess.run(command, cwd=root, env=environment, capture_output=True, text=True, encoding="utf-8")
        manifest["generator_exit_code"] = completed.returncode
        log = root / "logs/task1_generation.log"
        log.parent.mkdir(parents=True, exist_ok=True)
        log.write_text("COMMAND " + json.dumps(command) + "\n\nSTDOUT\n" + completed.stdout +
                       "\nSTDERR\n" + completed.stderr + "\n", encoding="utf-8")
        manifest.update(log="logs/task1_generation.log", log_sha256=digest(log))
        print(completed.stdout, end="", flush=True)
        if completed.returncode:
            print(completed.stderr, file=sys.stderr)
            raise RuntimeError(f"Generator exited with code {completed.returncode}")
        if before != {name: digest(root / name) for name in sources}:
            raise RuntimeError("Generator changed a protected input")

        manifest.update(stage="validation", validation_result="RUNNING")
        write_report(report_path, manifest)
        write_report(validation_path, {"result": "RUNNING", "started_utc": started})
        result = validate(root, output)
        manifest["output_sha256"] = {name: digest(output / name) for name in OUTPUT_NAMES}
        write_report(validation_path, {**result, "started_utc": started})
        manifest.update(result="PASS", stage="complete", validation_result="PASS",
                        finished_utc=datetime.now(timezone.utc).isoformat())
        write_report(report_path, manifest)
    except (Exception, KeyboardInterrupt) as exc:
        error = str(exc) or type(exc).__name__
        failed = {"result": "FAIL", "stage": manifest["stage"], "error": error,
                  "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat()}
        if manifest["stage"] == "preflight":
            write_report(preflight_path, failed)
        validation_status = "FAIL" if manifest["stage"] == "validation" else "NOT_RUN"
        write_report(validation_path, {**failed, "result": validation_status})
        manifest.update(failed, validation_result=validation_status)
        write_report(report_path, manifest)
        raise
    print(f"Task 1 PASS: {result['charging_sessions']} sessions; {result['meter_events']} meter readings")


if __name__ == "__main__":
    main()
