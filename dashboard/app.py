"""Interactive NSW station map and live MQTT projection for Task 3."""
from html import escape
import sys
import re
import json
from pathlib import Path

import duckdb
import folium
from folium.plugins import MarkerCluster
from streamlit_folium import st_folium
import pandas as pd
import plotly.express as px
import streamlit as st

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from task3_state import project
from integrated_runtime import DashboardRuntime
from analytics_queries import AnalyticsQueries
from analytics_storage import DEFAULT_DATABASE

st.set_page_config(page_title="NSW EV Charging Live", page_icon="⚡", layout="wide")
st.title("NSW EV Charging")
st.caption("COMP5339 A2 · Task 3 · Synthetic replay; event time is UTC (NEM source uses fixed UTC+10)")

# Top controls keep the map full-width; no sidebar.
mode_col, run_col, refresh_col, action_col = st.columns([1.7, 2.5, 1.6, 1.1], vertical_alignment="bottom")
with mode_col:
    mode = st.selectbox("View", ["Live demonstration", "Historical replay"])
with run_col:
    if mode == "Live demonstration":
        run_id = st.text_input("Run ID", value="", placeholder="Enter new live run ID",
                               help="Use exactly the same ID in the Publisher terminal.")
    else:
        run_id = st.text_input("Run ID", value="integration-demo-01",
                               help="Select a previously stored run.")
with refresh_col:
    refresh = st.toggle("Auto-refresh (5s)", value=True,
                        help="Turn off temporarily to interact with map popups.")
with action_col:
    if st.button("Refresh now", use_container_width=True):
        st.rerun()
st.caption("Broker → MQTT Publisher → DuckDB Subscriber → Live Map · Start Publisher only after SUBACK.")

@st.cache_data
def metadata():
    with duckdb.connect(str(ROOT / "database/charger_metadata.duckdb"), read_only=True) as db:
        sites = db.execute("SELECT station_id, station_name, address, latitude, longitude FROM stations").df()
        chargers = db.execute("SELECT charger_id, station_id, operator_standard, number_of_plugs, connector_types FROM chargers").df()
    return sites, chargers

sites, chargers = metadata()

@st.cache_resource
def runtime_manager():
    import threading
    class Manager:
        def __init__(self):
            self.lock = threading.Lock()
            self.runtime = None
        def stop(self):
            with self.lock:
                if self.runtime is not None:
                    self.runtime.close()
                    self.runtime = None
        def get(self, selected_run):
            with self.lock:
                if self.runtime is None or self.runtime.run_id != selected_run:
                    if self.runtime is not None:
                        self.runtime.close()
                    self.runtime = DashboardRuntime(selected_run)
                return self.runtime
    return Manager()


def historical_snapshot(selected_run):
    """Read committed history directly, without starting an MQTT subscriber.

    Called only when the live worker has released its DuckDB connection.
    """
    if not DEFAULT_DATABASE.is_file():
        raise FileNotFoundError(f"Analytics database missing: {DEFAULT_DATABASE}")
    with duckdb.connect(str(DEFAULT_DATABASE), read_only=True) as db:
        with AnalyticsQueries(connection=db) as queries:
            rows = db.execute(
                "SELECT payload FROM mqtt_events WHERE run_id=? ORDER BY sequence",
                [selected_run],
            ).fetchall()
            events = [json.loads(row[0]) for row in rows]
            metrics = queries.get_run_metrics(selected_run) if events else None
    return {"events": events, "metrics": metrics, "ready": False,
            "received_packets": 0, "saved_events": len(events), "pending": 0}


@st.fragment(run_every="5s" if refresh else None)
def live():
    if not run_id.strip():
        st.info("Enter a new Live run ID above, then start the Publisher with exactly the same ID. Historical records remain available under Historical replay.")
        return
    if not re.fullmatch(r"[A-Za-z0-9_-]{1,160}", run_id):
        st.warning("Run ID must contain only letters, digits, underscores or hyphens.")
        return
    try:
        if mode == "Historical replay":
            runtime_manager().stop()
            snapshot = historical_snapshot(run_id)
        else:
            runtime = runtime_manager().get(run_id)
            snapshot = runtime.snapshot()
        events = snapshot["events"]
        state = project(events)
        db_metrics = snapshot["metrics"]
    except (RuntimeError, TimeoutError, ValueError, OSError, duckdb.Error) as exc:
        st.error(f"DuckDB runtime: {exc}")
        return
    if mode == "Historical replay":
        st.caption(f"Historical DuckDB snapshot · Run: {run_id} · Stored events: {snapshot['saved_events']} · No MQTT Broker required")
    else:
        st.caption(f"Receiver: {'SUBSCRIBED' if snapshot['ready'] else 'CONNECTING'} · Run: {run_id} · MQTT packets: {snapshot['received_packets']} · DuckDB committed: {snapshot['saved_events']} · Pending sequence buffer: {snapshot['pending']}")
        if not snapshot["ready"]:
            st.info("Connecting to MQTT; wait for SUBACK before publishing.")
    if not events:
        st.info("No events received for selected run.")
        return
    if state["total"] != state["applied"]:
        st.warning(f"Waiting for missing sequence #{state['next_sequence']}. Received {state['total']} unique events; applied {state['applied']}.")
    a,b,c,d = st.columns(4)
    a.metric("Applied events", state["applied"])
    b.metric("Active sessions", db_metrics["active_sessions"])
    c.metric("Completed sessions", db_metrics["completed_sessions"])
    d.metric("Completed energy (kWh)", f"{db_metrics['completed_energy_kwh']:,.2f}")
    st.caption("KPIs are queried from DuckDB for this replay (including warmup), not the full generated day. End-of-window sessions remain active.")
    active_count = {}
    for e in state["active"].values():
        active_count[e["charger_id"]] = active_count.get(e["charger_id"], 0) + 1
    details = chargers.copy()
    details["Latest price (AUD/kWh)"] = details["charger_id"].map(state["prices"])
    details["Active plugs"] = details["charger_id"].map(active_count).fillna(0).astype(int)
    details = details.merge(sites, on="station_id", how="left")
    details = details[details["station_id"].isin(state["station_ids"])]
    if details.empty:
        st.info("No matching station metadata for this replay.")
        return
    station_counts = details.groupby("station_id")["Active plugs"].sum()
    geo = sites[sites["station_id"].isin(details["station_id"])].copy()
    geo["active"] = geo["station_id"].map(station_counts).fillna(0).astype(int)
    geo["status"] = geo["active"].map(lambda n: "Occupied" if n else "No active session")
    # Native Leaflet popups satisfy the Task 3 marker-click requirement.
    # Keep OpenStreetMap tiles and the existing NSW initial viewport.
    m = folium.Map(location=[-33.6, 150.9], zoom_start=7,
                   tiles="OpenStreetMap", control_scale=True, prefer_canvas=True)
    cluster = MarkerCluster(name="Charging stations", options={"showCoverageOnHover": False, "maxClusterRadius": 36, "spiderfyOnMaxZoom": True}).add_to(m)
    for site in geo.itertuples(index=False):
        site_rows = details.loc[details["station_id"] == site.station_id].sort_values("charger_id")
        charger_info = []
        for _, charger in site_rows.iterrows():
            raw_price = charger["Latest price (AUD/kWh)"]
            price = f"AUD {float(raw_price):.2f}/kWh" if pd.notna(raw_price) else "Not received yet"
            plugs = int(charger["number_of_plugs"])
            plug_types = str(charger["connector_types"] or "Unknown").replace("|", ", ")
            charger_info.append(
                "<div style='border-top:1px solid #e5e7eb;padding-top:7px;margin-top:7px'>"
                f"<b>Operator:</b> {escape(str(charger['operator_standard']))}<br>"
                f"<details style='margin:4px 0'><summary style='cursor:pointer;color:#555'>Charger ID</summary>"
                f"<code style='display:block;font-size:10px;overflow-wrap:anywhere;margin-top:3px'>{escape(str(charger['charger_id']))}</code></details>"
                f"<b>Plugs:</b> {plugs} · <b>Occupied:</b> {int(charger['Active plugs'])}<br>"
                f"<b>Plug types:</b> {escape(plug_types)}<br>"
                f"<b>Latest price:</b> {escape(price)}</div>"
            )
        popup_html = (
            "<div style='font:13px/1.45 Arial,sans-serif;width:260px;max-width:280px;padding:2px;color:#222'>"
            f"<strong style='font-size:15px'>{escape(str(site.station_name))}</strong><br>"
            f"<b>Address:</b> {escape(str(site.address))}<br>"
            + "".join(charger_info) + "</div>"
        )
        # MarkerCluster supports L.Marker, not Leaflet CircleMarker (Path).
        # A DivIcon gives the marker a compact dot while preserving a generous click target.
        color = "#b45309" if site.active else "#2563eb"
        dot_icon = folium.DivIcon(
            icon_size=(20, 20), icon_anchor=(10, 10),
            html=(
                "<div style='width:20px;height:20px;display:flex;"
                "align-items:center;justify-content:center;cursor:pointer'>"
                f"<span style='display:block;width:9px;height:9px;border-radius:50%;"
                f"background:{color};border:1px solid white;"
                "box-shadow:0 0 0 1px rgba(0,0,0,.12)'></span></div>"
            ),
        )
        folium.Marker(
            location=[float(site.latitude), float(site.longitude)],
            icon=dot_icon,
            tooltip=str(site.station_name),
            popup=folium.Popup(popup_html, max_width=315, min_width=265),
        ).add_to(cluster)
    st_folium(m, height=510, use_container_width=True, key="task3_station_map",
              returned_objects=[])
    # Show human-friendly station names while keeping the original station IDs internally.
    # Append a short numeric label only for duplicate names.
    name_counts = geo["station_name"].value_counts()
    station_labels = {
        (f"{row.station_name} · Station {i:03d}" if name_counts[row.station_name] > 1 else row.station_name): row.station_id
        for i, row in enumerate(geo.sort_values(["station_name", "station_id"]).itertuples(index=False), start=1)
    }
    selected = st.selectbox("Station details", list(station_labels), index=0)
    sid = station_labels[selected]
    st.write("**Address:**", geo.loc[geo["station_id"] == sid, "address"].iloc[0])
    station_chargers = details.loc[details["station_id"] == sid,
        ["charger_id", "operator_standard", "number_of_plugs", "connector_types",
         "Latest price (AUD/kWh)", "Active plugs"]].copy()
    station_chargers = station_chargers.sort_values("charger_id").reset_index(drop=True)
    station_chargers["connector_types"] = station_chargers["connector_types"].fillna("").str.replace("|", ", ", regex=False)
    station_chargers = station_chargers.rename(columns={
        "operator_standard": "Operator", "number_of_plugs": "Plugs",
        "connector_types": "Connector Types", "Latest price (AUD/kWh)": "Price (AUD/kWh)",
        "Active plugs": "Occupied", "charger_id": "Charger ID"
    })
    station_chargers = station_chargers[
        ["Charger ID", "Operator", "Plugs", "Connector Types", "Price (AUD/kWh)", "Occupied"]
    ]
    st.dataframe(station_chargers, use_container_width=True, hide_index=True)
    st.subheader("Charging progress")
    sessions = {**state["completed"], **state["active"]}
    sessions_with_readings = [e for e in sessions.values() if state["meters"].get(e["session_id"])]
    if not sessions_with_readings:
        st.info("No meter readings received yet. Wait for Publisher to send meter events (or press Refresh).")
        return
    session_numbers = {
        session_id: i
        for i, session_id in enumerate(
            sorted(sessions, key=lambda x: (sessions[x]["sequence"], x)), start=1
        )
    }
    # By default limit the dropdown to the station already selected above.
    # Search/status filters also work across the whole run without a 4,000-item list.
    ctrl1, ctrl2 = st.columns([1, 1])
    with ctrl1:
        all_stations = st.toggle("Search all stations", value=False, key="session_all_stations")
    with ctrl2:
        status_filter = st.selectbox("Session status", ["All", "Active", "Completed"],
                                     key="session_status_filter")
    search_term = st.text_input("Find session", placeholder="Enter session number, e.g. 120",
                                key="session_search").strip().lower()
    candidates = sessions_with_readings if all_stations else [
        e for e in sessions_with_readings if e["station_id"] == sid
    ]
    candidates = [
        e for e in candidates
        if (status_filter == "All" or
            (e["session_id"] in state["active"]) == (status_filter == "Active"))
        and (not search_term or
             search_term in str(session_numbers[e["session_id"]]) or
             search_term in str(e["connector_id"]).lower())
    ]
    candidates.sort(key=lambda e: (session_numbers[e["session_id"]], e["session_id"]))
    if not candidates:
        st.info("No matching sessions with meter readings. Try Search all stations or clear the filters.")
        return
    if len(candidates) > 100:
        st.caption(f"{len(candidates):,} matching sessions. Showing the first 100; enter a session number to narrow results.")
        candidates = candidates[:100]
    options = {
        f"Session {session_numbers[e['session_id']]:04d} · Connector {e['connector_id']} · "
        f"{'Active' if e['session_id'] in state['active'] else 'Completed'}": e["session_id"]
        for e in candidates
    }
    chosen = st.selectbox("Session with meter readings", list(options), key="task3_session")
    readings = state["meters"][options[chosen]]
    df = pd.DataFrame(readings).sort_values("event_time")
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
    metric = st.radio("Live meter curve", ["energy_kwh", "power_kw"], horizontal=True,
                      format_func=lambda x: "Cumulative energy (kWh)" if x=="energy_kwh" else "Power (kW)")
    fig2 = px.line(df, x="event_time", y=metric, markers=True, title="Charging progress")
    st.plotly_chart(fig2, use_container_width=True, key="task3_meter_curve")
    st.caption(f"{len(readings)} meter readings · session status: {'Active' if options[chosen] in state['active'] else 'Completed'}")

live()
