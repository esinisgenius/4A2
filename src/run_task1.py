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

from validate_task1 import AEMO_NAME, AEMO_URL, OUTPUT_NAMES, ROOT, digest, validate, validate_aemo


def main() -> None:
    output = ROOT / "data/generated"
    cache = output / "aemo_cache" / AEMO_NAME
    cache.parent.mkdir(parents=True, exist_ok=True)
    downloaded = not cache.exists()
    if downloaded:
        request = urllib.request.Request(AEMO_URL, headers={"User-Agent": "Mozilla/5.0"})
        with urllib.request.urlopen(request, timeout=60) as response:
            raw = response.read()
        cache.write_bytes(raw)
    preflight, _ = validate_aemo(cache)
    (ROOT / "docs/task1_aemo_validation.json").write_text(json.dumps(preflight, indent=2) + "\n", encoding="utf-8")
    print(f"AEMO preflight PASS: {preflight['intervals']} five-minute intervals", flush=True)

    command = [sys.executable, "vendor/data_generator/generate_dataset.py",
               "--stations", "data/input/stations.csv", "--start", "2026-09-15", "--days", "1",
               "--out", "data/generated", "--seed", "5339", "--sessions-per-connector-day", "3", "2"]
    sources = ["data/input/stations.csv", "data/processed/generator_station_mapping.csv",
               "data/processed/stations_prepared.csv", "data/processed/chargers_prepared.csv",
               "vendor/data_generator/generate_dataset.py"]
    before = {name: digest(ROOT / name) for name in sources}
    started = datetime.now(timezone.utc).isoformat()
    environment = os.environ.copy()
    environment["PYTHONUTF8"] = "1"
    environment["PYTHONIOENCODING"] = "utf-8"
    completed = subprocess.run(command, cwd=ROOT, env=environment, capture_output=True, text=True, encoding="utf-8")
    log = ROOT / "logs/task1_generation.log"
    log.parent.mkdir(parents=True, exist_ok=True)
    log.write_text("COMMAND " + json.dumps(command) + "\n\nSTDOUT\n" + completed.stdout +
                   "\nSTDERR\n" + completed.stderr + "\n", encoding="utf-8")
    manifest = {
        "started_utc": started, "finished_utc": datetime.now(timezone.utc).isoformat(),
        "command": command, "cwd": str(ROOT), "python": platform.python_version(),
        "seed": 5339, "start": "2026-09-15", "days": 1, "sessions_per_connector_day": [3, 2],
        "other_generator_options": "unchanged teacher defaults; dynamic AEMO prices; meter_every=1",
        "text_encoding": "UTF-8 (PYTHONUTF8=1 and PYTHONIOENCODING=utf-8)",
        "aemo_downloaded_by_this_run": downloaded, "aemo_url": AEMO_URL,
        "aemo_sha256": digest(cache), "input_sha256": before,
        "generator_exit_code": completed.returncode, "log": "logs/task1_generation.log", "log_sha256": digest(log),
    }
    report_path = ROOT / "docs/task1_run.json"
    report_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(completed.stdout, end="", flush=True)
    if completed.returncode:
        print(completed.stderr, file=sys.stderr)
        raise SystemExit(completed.returncode)
    if before != {name: digest(ROOT / name) for name in sources}:
        raise RuntimeError("Generator changed a protected input")
    result = validate(ROOT, output)
    (ROOT / "docs/task1_validation.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    manifest["validation_result"] = result["result"]
    manifest["output_sha256"] = {name: digest(output / name) for name in OUTPUT_NAMES}
    report_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    print(f"Task 1 PASS: {result['charging_sessions']} sessions; {result['meter_events']} meter readings")


if __name__ == "__main__":
    main()
