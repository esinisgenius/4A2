"""Interactive NSW station map and live MQTT projection for Task 3."""
import sqlite3
from html import escape
import sys
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
from task3_state import load, project

st.set_page_config(page_title="NSW EV Charging Live", page_icon="⚡", layout="wide")
st.title("NSW EV Charging — Live Dashboard")
st.caption("COMP5339 A2 · Task 3 · Synthetic replay; event time is UTC (NEM source uses fixed UTC+10)")

with st.sidebar:
    run_id = st.text_input("Replay run ID", value="team-demo-01")
    journal = st.text_input("Subscriber journal", value=str(ROOT / "database/task3_events.sqlite"))
    refresh = st.toggle("Auto-refresh every 5 seconds", value=False, help="Off by default to prevent map tile flashing; click Refresh to load new events.")
    if st.button("Refresh events now"):
        st.rerun()
    st.info("Start subscriber and wait for SUBACK before launching publisher. Each new replay requires a new run ID.")

@st.cache_data
def metadata():
    with duckdb.connect(str(ROOT / "database/charger_metadata.duckdb"), read_only=True) as db:
        sites = db.execute("SELECT station_id, station_name, address, latitude, longitude FROM stations").df()
        chargers = db.execute("SELECT charger_id, station_id, operator_standard, number_of_plugs, connector_types FROM chargers").df()
    return sites, chargers

sites, chargers = metadata()

@st.fragment(run_every="5s" if refresh else None)
def live():
    if not run_id or not Path(journal).exists():
        st.warning("No events yet. Start src/subscriber.py with the matching --run-id, then publish.")
        return
    try:
        con = sqlite3.connect(f"file:{Path(journal).resolve()}?mode=ro", uri=True, timeout=3)
        events = load(con, run_id)
        con.close()
        state = project(events)
    except (sqlite3.Error, ValueError) as exc:
        st.error(f"Could not read valid replay state: {exc}")
        return
    if not events:
        st.info("Subscriber journal exists, but selected run has no events.")
        return
    if state["total"] != state["applied"]:
        st.warning(f"Waiting for missing sequence #{state['next_sequence']}. Received {state['total']} unique events; applied {state['applied']}.")
    a,b,c,d = st.columns(4)
    a.metric("Applied events", state["applied"])
    b.metric("Active sessions", len(state["active"]))
    c.metric("Completed sessions", len(state["completed"]))
    d.metric("Completed energy (kWh)", f"{sum(x['energy_kwh'] for x in state['completed'].values()):,.2f}")
    st.caption("Metrics are for this selected replay only, including its warmup; not the full generated day. End-of-window active sessions remain active.")
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
    st.subheader("Charging progress — all sessions in selected run")
    sessions = {**state["completed"], **state["active"]}
    sessions_with_readings = [e for e in sessions.values() if state["meters"].get(e["session_id"])]
    if not sessions_with_readings:
        st.info("No meter readings received yet. Wait for Publisher to send meter events (or press Refresh).")
        return
    station_first = [e for e in sessions_with_readings if e["station_id"] == sid]
    ordered = station_first + [e for e in sessions_with_readings if e["station_id"] != sid]
    # Human-readable labels are scoped to the current replay and stable as new events arrive.
    # The original session_id remains the unique internal key for MQTT/state lookup.
    session_numbers = {
        session_id: i
        for i, session_id in enumerate(
            sorted(sessions, key=lambda sid: (sessions[sid]["sequence"], sid)), start=1
        )
    }
    options = {
        f"Session {session_numbers[e['session_id']]:03d} · Connector {e['connector_id']} · "
        f"{'Active' if e['session_id'] in state['active'] else 'Completed'}": e["session_id"]
        for e in ordered
    }
    chosen = st.selectbox("Session with meter readings", options.keys(), key="task3_session")
    readings = state["meters"][options[chosen]]
    df = pd.DataFrame(readings).sort_values("event_time")
    df["event_time"] = pd.to_datetime(df["event_time"], utc=True)
    metric = st.radio("Live meter curve", ["energy_kwh", "power_kw"], horizontal=True,
                      format_func=lambda x: "Cumulative energy (kWh)" if x=="energy_kwh" else "Power (kW)")
    fig2 = px.line(df, x="event_time", y=metric, markers=True, title="Charging progress")
    st.plotly_chart(fig2, use_container_width=True, key="task3_meter_curve")
    st.caption(f"{len(readings)} meter readings · session status: {'Active' if options[chosen] in state['active'] else 'Completed'}")

live()
