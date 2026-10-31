"""Check that the Canvas ZIP contains the essential COMP5339 A2 deliverables.

Usage: python scripts/check_submission.py path/to/submission.zip
Checks file presence and nonempty payload sizes; does not prove runtime correctness.
"""
import sys
import zipfile
from pathlib import Path

REQUIRED = (
    "README.md",
    "requirements.txt",
    "dashboard/app.py",
    "src/local_broker.py",
    "src/publisher.py",
    "src/prepare_events.py",
    "src/integrated_runtime.py",
    "src/analytics_storage.py",
    "src/analytics_subscriber.py",
    "src/analytics_queries.py",
    "database/analytics_schema.sql",
    "database/charger_metadata.duckdb",
    "database/charger_analytics.duckdb",
    "data/events/full/events.json",
    "data/events/full/manifest.json",
    "data/events/mqtt_demo/events.json",
    "data/generated/stations.csv",
    "data/generated/prices_hourly.csv",
    "data/generated/sessions.csv",
    "data/generated/session_metering.csv",
)
FORBIDDEN = (".venv/", "__pycache__/", ".git/", ".env", "database/task3_events.sqlite")


def main():
    if len(sys.argv) != 2:
        raise SystemExit("Usage: python scripts/check_submission.py <submission.zip>")
    path = Path(sys.argv[1])
    if not path.is_file() or not zipfile.is_zipfile(path):
        raise SystemExit(f"FAIL: not a ZIP file: {path}")
    with zipfile.ZipFile(path) as zf:
        if zf.testzip() is not None:
            raise SystemExit("FAIL: ZIP CRC test failed")
        members = {name: info for name, info in ((i.filename, i) for i in zf.infolist())
                   if not info.is_dir()}
        # Allow the ZIP to contain one top-level project folder.
        names = list(members)
        base = ""
        if not all(req in members for req in REQUIRED):
            prefixes = {name.split("/", 1)[0] + "/" for name in names if "/" in name}
            for prefix in prefixes:
                if all(prefix + req in members for req in REQUIRED):
                    base = prefix
                    break
        problems = []
        for req in REQUIRED:
            info = members.get(base + req)
            if info is None or info.file_size <= 0:
                problems.append(f"missing/empty: {req}")
        for name in names:
            rel = name[len(base):] if name.startswith(base) else name
            if any(part in rel for part in FORBIDDEN):
                problems.append(f"exclude sensitive/unneeded file: {name}")
        full = members.get(base + "data/events/full/events.json")
        if full is not None and full.file_size != 79656551:
            problems.append(f"full events expected 79656551 bytes, found {full.file_size}")
        if problems:
            for issue in problems:
                print("FAIL:", issue)
            raise SystemExit(1)
        print(f"PASS archive structure: {len(REQUIRED)} essential files, "
              f"{len(members)} total files")
        print("Note: verify complete Python environment and MQTT live path separately.")


if __name__ == "__main__":
    main()
