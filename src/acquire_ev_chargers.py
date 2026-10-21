from pathlib import Path
import re

import pandas as pd
import requests


API_URL = "https://data.gov.au/data/api/3/action/package_show?id=nsw-2-ev-charging-locations"
OUTPUT_DIR = Path(__file__).resolve().parents[1] / "data" / "source"


def select_december_2025_resource(resources):
    """Select the latest CSV whose official resource URL contains a December 2025 date."""
    candidates = []

    for resource in resources:
        url = resource.get("url", "")
        if resource.get("state", "active") != "active":
            continue
        if resource.get("format", "").upper() != "CSV" and not url.lower().endswith(".csv"):
            continue

        match = re.search(r"202512(\d{2})", url)
        if match:
            version = f"2025-12-{match.group(1)}"
            candidates.append((version, resource))

    if not candidates:
        raise RuntimeError("No December 2025 EV charger CSV was found in the official catalogue.")

    return max(candidates, key=lambda item: item[0])


def main():
    catalogue_response = requests.get(API_URL, timeout=30)
    catalogue_response.raise_for_status()
    catalogue = catalogue_response.json()

    if not catalogue.get("success"):
        raise RuntimeError("The data.gov.au catalogue request was unsuccessful.")

    version, resource = select_december_2025_resource(catalogue["result"]["resources"])
    output_path = OUTPUT_DIR / f"ev_charging_locations_nsw_{version.replace('-', '')}.csv"
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    download_response = requests.get(resource["url"], timeout=60)
    download_response.raise_for_status()
    output_path.write_bytes(download_response.content)

    chargers = pd.read_csv(output_path)
    if chargers.empty:
        raise RuntimeError("The downloaded EV charger dataset is empty.")

    print(f"Selected version: {version}")
    print(f"Saved to: {output_path}")
    print(f"Rows: {len(chargers)}")
    print(f"Columns: {', '.join(chargers.columns)}")


if __name__ == "__main__":
    main()
