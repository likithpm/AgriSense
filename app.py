"""Streamlit dashboard for AgriSense AI two-stage smart crop advisory."""

from __future__ import annotations

import logging
from typing import Any
import folium
import pandas as pd
import streamlit as st
import streamlit.components.v1 as components
from streamlit_folium import st_folium

from services.farm_advisor_service import analyze_farm, generate_crop_detailed_plan
from services.location_service import get_coordinates, get_location_from_coordinates

logger = logging.getLogger(__name__)

# Default Map Center (India)
INDIA_LAT = 22.5937
INDIA_LON = 78.9629
INDIA_ZOOM = 5

st.set_page_config(
    page_title="AgriSense AI - Smart Crop Advisory",
    page_icon="🌱",
    layout="wide",
    initial_sidebar_state="expanded",
)

st.markdown(
    """
    <style>
    :root {
        --agri-green: #1f6f52;
        --agri-green-light: #2e8b67;
        --agri-dark: #163a2d;
        --agri-mint: #e8f3ed;
        --agri-gold: #d89b3d;
        --agri-ink: #20322b;
        --agri-card-bg: #ffffff;
    }
    .stApp { background: #f6f8f5; color: var(--agri-ink); }
    [data-testid="stSidebar"] { background: var(--agri-dark); }
    [data-testid="stSidebar"] * { color: #f4faf6 !important; }
    
    .hero {
        background: linear-gradient(135deg, #163a2d 0%, #1f6f52 65%, #387b5a 100%);
        color: white;
        padding: 1.8rem 2.2rem;
        border-radius: 14px;
        margin-bottom: 1.2rem;
        box-shadow: 0 8px 24px rgba(22, 58, 45, .14);
    }
    .hero h1 { margin: 0; font-size: 2.2rem; letter-spacing: -0.02em; font-weight: 700; }
    .hero p { margin: .35rem 0 0; color: #d9eee1; font-size: 1.05rem; }

    .stage-badge {
        display: inline-block;
        background: #2e8b67;
        color: white;
        padding: 4px 12px;
        border-radius: 20px;
        font-size: 0.82rem;
        font-weight: 700;
        letter-spacing: 0.05em;
        text-transform: uppercase;
        margin-bottom: 0.5rem;
    }

    .section-label {
        color: var(--agri-green); font-size: .88rem; font-weight: 800;
        letter-spacing: .08em; margin: 1.4rem 0 .5rem; text-transform: uppercase;
    }

    .selection-card {
        background: white;
        border: 2px solid #2e8b67;
        border-radius: 10px;
        padding: 1rem 1.25rem;
        margin-bottom: 1rem;
        box-shadow: 0 4px 14px rgba(46, 139, 103, 0.1);
    }

    .crop-card {
        background: white;
        border: 1px solid #dce9df;
        border-radius: 14px;
        padding: 1.4rem 1.5rem;
        box-shadow: 0 6px 18px rgba(22, 58, 45, 0.06);
        transition: transform 0.2s ease, box-shadow 0.2s ease;
        margin-bottom: 1rem;
        height: 100%;
        display: flex;
        flex-direction: column;
        justify-content: space-between;
    }
    .crop-card:hover {
        transform: translateY(-3px);
        box-shadow: 0 10px 25px rgba(31, 111, 82, 0.15);
        border-color: #2e8b67;
    }
    .crop-card.selected-active {
        border: 2.5px solid #1f6f52;
        background: #fbfdfc;
        box-shadow: 0 8px 24px rgba(31, 111, 82, 0.2);
    }

    .crop-title-row {
        display: flex;
        justify-content: space-between;
        align-items: center;
        margin-bottom: 0.8rem;
    }
    .crop-title {
        font-size: 1.45rem;
        font-weight: 800;
        color: #163a2d;
        margin: 0;
    }
    .score-pill {
        background: #e8f3ed;
        color: #1f6f52;
        padding: 4px 10px;
        border-radius: 12px;
        font-weight: 800;
        font-size: 0.9rem;
        border: 1px solid #c2e0cf;
    }

    .profit-highlight {
        background: #f3f9f5;
        border-left: 4px solid #2e8b67;
        padding: 0.75rem 1rem;
        border-radius: 6px;
        margin: 0.8rem 0;
    }
    .profit-val {
        font-size: 1.25rem;
        font-weight: 800;
        color: #163a2d;
    }
    .profit-sub {
        font-size: 0.82rem;
        color: #4f6358;
    }

    .suitability-tag {
        font-size: 0.82rem;
        color: #3f554a;
        background: #f0f4f1;
        padding: 6px 10px;
        border-radius: 6px;
        margin-bottom: 1rem;
    }

    .vendor-card {
        background: white; border: 1px solid #dce9df; border-radius: 10px;
        padding: 1.1rem; min-height: 10rem; box-shadow: 0 4px 14px rgba(22, 58, 45, .05);
    }
    .vendor-card h4 { color: var(--agri-dark); margin: 0 0 .4rem; }
    .muted { color: #6b7e73; font-size: .88rem; }
    </style>
    """,
    unsafe_allow_html=True,
)


def _render_gps_bridge() -> None:
    """Lightweight HTML5 Geolocation trigger to capture device GPS."""
    gps_html = """
    <div style="margin-bottom: 8px;">
        <button id="gpsBtn" onclick="getLocation()" style="
            background: #1f6f52;
            color: white;
            border: none;
            padding: 9px 16px;
            border-radius: 8px;
            font-size: 13px;
            font-weight: 600;
            cursor: pointer;
            width: 100%;
            display: flex;
            align-items: center;
            justify-content: center;
            gap: 6px;
            box-shadow: 0 2px 6px rgba(0,0,0,0.15);
        ">📍 Use Current GPS Location</button>
    </div>
    <script>
    function getLocation() {
        var btn = document.getElementById("gpsBtn");
        btn.innerText = "⏳ Detecting GPS coordinates...";
        if (navigator.geolocation) {
            navigator.geolocation.getCurrentPosition(
                function(pos) {
                    var lat = pos.coords.latitude;
                    var lon = pos.coords.longitude;
                    btn.innerText = "✅ Location Captured!";
                    var searchParams = new URLSearchParams(window.parent.location.search);
                    searchParams.set("gps_lat", lat);
                    searchParams.set("gps_lon", lon);
                    window.parent.location.search = searchParams.toString();
                },
                function(err) {
                    alert("GPS location could not be determined: " + err.message);
                    btn.innerText = "📍 Use Current GPS Location";
                },
                { enableHighAccuracy: true, timeout: 10000 }
            );
        } else {
            alert("Geolocation is not supported by your browser.");
            btn.innerText = "📍 Use Current GPS Location";
        }
    }
    </script>
    """
    components.html(gps_html, height=52)


def _value(data: dict[str, Any], key: str, default: str = "Unavailable") -> Any:
    """Return a display-safe backend value."""
    value = data.get(key)
    return default if value is None or value == "" else value


def _show_metric_row(items: list[tuple[str, Any, str]]) -> None:
    """Render a row of Streamlit metrics."""
    columns = st.columns(len(items))
    for column, (label, value, delta) in zip(columns, items):
        column.metric(label, value, delta=delta or None)


def _show_table(rows: Any, columns: list[str]) -> None:
    """Render backend rows as a table, or an empty-state message."""
    valid_rows = [row for row in rows if isinstance(row, dict)] if isinstance(rows, list) else []
    if not valid_rows:
        st.info("No data available.")
        return
    table = pd.DataFrame(valid_rows)
    available = [column for column in columns if column in table.columns]
    st.dataframe(table[available], use_container_width=True, hide_index=True)


def _render_environment_overview(stage1_data: dict[str, Any]) -> None:
    """Render location, weather telemetry, soil health, and NPK nutrients."""
    location = stage1_data.get("location") or {}
    weather = stage1_data.get("weather") or {}
    soil = stage1_data.get("soil") or {}
    npk = stage1_data.get("npk") or {}

    st.markdown('<div class="section-label">🌿 Farmland Environmental Telemetry</div>', unsafe_allow_html=True)
    loc_display = location.get("location_name") or location.get("location") or "Selected Farm Region"
    
    col1, col2, col3, col4 = st.columns(4)
    col1.metric("Location", loc_display)
    col2.metric("Temperature", f"{_value(weather, 'temperature')} °C")
    col3.metric("Humidity", f"{_value(weather, 'humidity')} %")
    col4.metric("Precipitation", f"{_value(weather, 'rainfall')} mm")

    left, right = st.columns(2)
    with left:
        with st.container(border=True):
            st.markdown("##### 🧪 Soil Properties")
            _show_metric_row([
                ("pH Level", _value(soil, "ph"), ""),
                ("Nitrogen Status", _value(soil, "nitrogen"), ""),
                ("Organic Carbon", _value(soil, "organic_carbon"), ""),
            ])
            st.caption(f"Texture Composition: Sand {_value(soil, 'sand')}% | Clay {_value(soil, 'clay')}% | Silt {_value(soil, 'silt')}%")
            if soil.get("soil_summary"):
                st.caption(f"**Agronomic Note:** {soil['soil_summary']}")
    with right:
        with st.container(border=True):
            st.markdown("##### ⚡ Estimated NPK Nutrient Profile")
            _show_metric_row([
                ("Nitrogen (N)", f"{_value(npk, 'N')} kg/ha", ""),
                ("Phosphorus (P)", f"{_value(npk, 'P')} kg/ha", ""),
                ("Potassium (K)", f"{_value(npk, 'K')} kg/ha", ""),
            ])
            st.caption("AI-modeled nutrient baseline from satellite soil data & climate conditions.")


def _render_stage1_crop_cards(top_3_crops: list[dict[str, Any]], farm_area: float) -> None:
    """Render the Top 3 Scored Crop Cards with 'Select Crop' action buttons."""
    st.markdown('<div class="section-label">🌾 Stage 1: Top 3 Crop Recommendations</div>', unsafe_allow_html=True)
    st.caption("Review the top-performing crops scored for your soil, local weather, and market profitability. Click **'Select Crop'** to generate a detailed cultivation & procurement plan.")

    if not top_3_crops:
        st.warning("No crop recommendations available for this region.")
        return

    cols = st.columns(3)
    for idx, crop in enumerate(top_3_crops[:3]):
        crop_name = crop.get("crop_name", f"Crop {idx+1}")
        score = crop.get("score", 75.0)
        curr_price = crop.get("current_price", 0.0)
        exp_price = crop.get("expected_price", curr_price)
        profit_per_acre = crop.get("profit_per_acre", 0.0)
        total_profit = crop.get("total_profit", profit_per_acre * farm_area)
        suitable_for = crop.get("suitable_for", "Well-suited for regional agro-climatic conditions")
        is_selected = (st.session_state.get("selected_crop") == crop_name)

        with cols[idx]:
            card_class = "crop-card selected-active" if is_selected else "crop-card"
            st.markdown(
                f"""
                <div class="{card_class}">
                    <div>
                        <div class="crop-title-row">
                            <span class="crop-title">{crop_name}</span>
                            <span class="score-pill">Score: {score:.0f}</span>
                        </div>
                        <div style="font-size: 0.88rem; color: #4f6358; margin-bottom: 6px;">
                            <b>Current Price:</b> ₹ {curr_price:,.0f} / Qtl<br>
                            <b>Expected Harvest Price:</b> ₹ {exp_price:,.0f} / Qtl
                        </div>
                        <div class="profit-highlight">
                            <div class="profit-val">₹ {profit_per_acre:,.0f} <span style="font-size: 0.85rem; font-weight: normal;">/ Acre</span></div>
                            <div class="profit-sub">Total Estimated Profit: <b>₹ {total_profit:,.0f}</b> ({farm_area} Acre{'s' if farm_area != 1 else ''})</div>
                        </div>
                        <div class="suitability-tag">
                            🌱 <b>Suitable For:</b> {suitable_for}
                        </div>
                    </div>
                </div>
                """,
                unsafe_allow_html=True,
            )

            # Button to select crop and trigger Stage 2
            btn_label = f"✅ Plan {crop_name}" if is_selected else f"🌱 Select {crop_name}"
            if st.button(
                btn_label,
                key=f"select_crop_btn_{idx}_{crop_name}",
                use_container_width=True,
                type="primary" if is_selected else "secondary",
            ):
                st.session_state["selected_crop"] = crop_name
                with st.spinner(f"Generating detailed 120-day plan, procurement inputs, and vendor discovery for {crop_name}..."):
                    stage1 = st.session_state.get("analysis_results", {})
                    loc_name = (
                        stage1.get("location", {}).get("location_name")
                        or stage1.get("location", {}).get("location")
                        or "Farmland"
                    )
                    detailed_plan = generate_crop_detailed_plan(
                        selected_crop=crop_name,
                        location_name=loc_name,
                        latitude=st.session_state.get("selected_lat"),
                        longitude=st.session_state.get("selected_lon"),
                        farm_area_acres=farm_area,
                        soil_data=stage1.get("soil"),
                        weather_data=stage1.get("weather"),
                        market_data=stage1.get("market_data"),
                    )
                    st.session_state["farm_plan"] = detailed_plan
                st.rerun()


def _render_stage2_detailed_plan(plan: dict[str, Any], farm_area: float) -> None:
    """Render Stage 2 detailed execution plan, scaled procurement, vendors, and financial breakdown."""
    crop_name = plan.get("selected_crop", "Selected Crop")
    profit_info = plan.get("profitability", {})
    cost_breakdown = plan.get("cost_breakdown", {})
    procurement = plan.get("procurement_plan", {})
    execution = plan.get("execution_plan", [])
    evidence = plan.get("evidence", [])

    st.markdown("---")
    st.markdown(
        f"""
        <div style="background: linear-gradient(135deg, #1f6f52 0%, #2e8b67 100%); color: white; padding: 1.2rem 1.6rem; border-radius: 12px; margin-bottom: 1.2rem;">
            <div style="font-size: 0.85rem; text-transform: uppercase; font-weight: 700; letter-spacing: 0.08em; opacity: 0.9;">Stage 2: Comprehensive Farm Advisory</div>
            <div style="font-size: 1.7rem; font-weight: 800; margin-top: 2px;">Detailed Cultivation & Procurement Plan: {crop_name}</div>
            <div style="font-size: 0.95rem; opacity: 0.95;">Customized for <b>{farm_area} Acres</b> of farmland in {plan.get('location_name', 'your region')}.</div>
        </div>
        """,
        unsafe_allow_html=True,
    )

    # Key Financial Summary Metrics
    m1, m2, m3, m4 = st.columns(4)
    m1.metric("Farm Land Area", f"{farm_area} Acres")
    m2.metric("Expected Total Yield", f"{round(profit_info.get('yield_per_acre', 0) * farm_area, 1)} Qtl")
    m3.metric("Estimated Total Cost", f"₹ {profit_info.get('total_cost', 0):,.2f}")
    m4.metric("Net Projected Profit", f"₹ {profit_info.get('total_profit', 0):,.2f}")

    # Cost Breakdown
    with st.expander("💰 Financial Breakdown & Profit Projection", expanded=True):
        fcol1, fcol2 = st.columns(2)
        with fcol1:
            st.markdown("##### 📊 Production Cost Breakdown")
            cost_df = pd.DataFrame([
                {"Cost Component": "Quality Seeds / Saplings (15%)", "Estimated Amount": f"₹ {cost_breakdown.get('seeds_cost', 0):,.2f}"},
                {"Cost Component": "Fertilizers, Soil & Bio-Nutrients (35%)", "Estimated Amount": f"₹ {cost_breakdown.get('fertilizer_soil_cost', 0):,.2f}"},
                {"Cost Component": "Machinery, Drip & Mulch (20%)", "Estimated Amount": f"₹ {cost_breakdown.get('machinery_irrigation_cost', 0):,.2f}"},
                {"Cost Component": "Labor, Weeding & Harvesting (30%)", "Estimated Amount": f"₹ {cost_breakdown.get('labor_operations_cost', 0):,.2f}"},
                {"Cost Component": "Total Cultivation Investment", "Estimated Amount": f"₹ {cost_breakdown.get('total_cost', 0):,.2f}"},
            ])
            st.dataframe(cost_df, use_container_width=True, hide_index=True)
        with fcol2:
            st.markdown("##### 📈 Revenue & Net Margin")
            rev_df = pd.DataFrame([
                {"Financial Metric": "Expected Market Price", "Value": f"₹ {profit_info.get('expected_price', 0):,.2f} / Quintal"},
                {"Financial Metric": "Estimated Yield / Acre", "Value": f"{profit_info.get('yield_per_acre', 0)} Quintals"},
                {"Financial Metric": "Gross Expected Revenue", "Value": f"₹ {profit_info.get('total_revenue', 0):,.2f}"},
                {"Financial Metric": "Total Production Cost", "Value": f"₹ {profit_info.get('total_cost', 0):,.2f}"},
                {"Financial Metric": "Estimated Net Profit", "Value": f"₹ {profit_info.get('total_profit', 0):,.2f}"},
            ])
            st.dataframe(rev_df, use_container_width=True, hide_index=True)

    # 120-Day Cultivation Execution Timeline
    with st.expander("📅 120-Day Cultivation Execution Timeline", expanded=True):
        _show_table(execution, ["day", "stage", "task", "description"])

    # Required Inputs & Materials Scaled to Acreage
    with st.expander(f"📦 Required Farm Inputs (Scaled for {farm_area} Acres)", expanded=True):
        _show_table(procurement.get("required_items", []), ["item", "quantity"])

    # Local and Online Vendors
    with st.expander("🏪 Nearby Agricultural Vendors & Online Suppliers", expanded=True):
        st.markdown("##### 📍 Nearby Local Mandis & Input Dealers")
        local = procurement.get("local_vendors", [])
        if local:
            cols = st.columns(min(3, len(local)))
            for i, vendor in enumerate(local):
                with cols[i % len(cols)]:
                    st.markdown(
                        f'<div class="vendor-card"><h4>{_value(vendor, "name")}</h4>'
                        f'<div>{_value(vendor, "address")}</div>'
                        f'<div class="muted">Rating: {_value(vendor, "rating", "N/A")}</div></div>',
                        unsafe_allow_html=True,
                    )
                    link = vendor.get("search_url") or vendor.get("maps_link")
                    if link:
                        st.link_button("📍 Open in Google Maps", link, use_container_width=True)
        else:
            st.info("No nearby local vendors discovered for this location.")

        st.markdown("##### 🌐 Certified Online Agricultural Portals")
        online = procurement.get("online_vendors", [])
        if online:
            cols = st.columns(min(3, len(online)))
            for i, vendor in enumerate(online):
                with cols[i % len(cols)]:
                    st.markdown(
                        f'<div class="vendor-card"><h4>{_value(vendor, "vendor_name")}</h4>'
                        f'<div class="muted">{_value(vendor, "product")}</div></div>',
                        unsafe_allow_html=True,
                    )
                    link = vendor.get("website") or vendor.get("url")
                    if link:
                        st.link_button("🌐 Visit Store", link, use_container_width=True)
        else:
            st.info("No online suppliers available.")

    # Agronomic Evidence & Rationale
    with st.expander("🌾 Agronomic Suitability & Scientific Rationale", expanded=False):
        if evidence:
            for item in evidence:
                st.markdown(f"- {item}")
        else:
            st.info("Agronomic evidence is standard for this crop type.")


def main() -> None:
    """Render the two-stage interactive dashboard."""
    # Process GPS query parameters if passed from HTML5 bridge
    if "gps_lat" in st.query_params and "gps_lon" in st.query_params:
        try:
            st.session_state["selected_lat"] = float(st.query_params["gps_lat"])
            st.session_state["selected_lon"] = float(st.query_params["gps_lon"])
            st.session_state["has_user_selected"] = True
            st.query_params.clear()
        except Exception:
            pass

    # Initialize Session State
    if "selected_lat" not in st.session_state:
        st.session_state["selected_lat"] = INDIA_LAT
    if "selected_lon" not in st.session_state:
        st.session_state["selected_lon"] = INDIA_LON
    if "farm_area_acres" not in st.session_state:
        st.session_state["farm_area_acres"] = 1.0
    if "has_user_selected" not in st.session_state:
        st.session_state["has_user_selected"] = False
    if "analysis_results" not in st.session_state:
        st.session_state["analysis_results"] = None
    if "selected_crop" not in st.session_state:
        st.session_state["selected_crop"] = None
    if "farm_plan" not in st.session_state:
        st.session_state["farm_plan"] = None

    st.markdown(
        '<div class="hero"><h1>🌱 AgriSense AI</h1>'
        '<p>Two-Stage Intelligent Agricultural Advisory & Farm Planning Platform</p></div>',
        unsafe_allow_html=True,
    )

    st.markdown("### 🗺️ Step 1 & 2: Select Location and Farm Area")
    st.caption("Pin your farmland on the map, use GPS, or search a location. Enter your farm acreage to begin Stage 1 analysis.")

    map_col, control_col = st.columns([1.7, 1.0])

    with control_col:
        with st.container(border=True):
            st.markdown("#### 📍 Location Tools")

            # Option 1: GPS
            _render_gps_bridge()

            st.markdown("---")

            # Option 2: Place Name Search
            search_query = st.text_input(
                "Search City / District",
                placeholder="e.g. Coimbatore, Nashik, Pune, Guntur",
            )
            if st.button("🔍 Search & Pin", use_container_width=True):
                if search_query.strip():
                    with st.spinner(f"Searching '{search_query}'..."):
                        geo = get_coordinates(search_query.strip())
                        if geo:
                            st.session_state["selected_lat"] = geo["latitude"]
                            st.session_state["selected_lon"] = geo["longitude"]
                            st.session_state["has_user_selected"] = True
                            st.success(f"Pinned: {geo['location_name']}")
                            st.rerun()
                        else:
                            st.error(f"Could not find coordinates for '{search_query}'.")

            st.markdown("---")

            # Step 2: Total Farm Area (Acres) Input
            st.markdown("#### 🌾 Land Area Input")
            farm_area = st.number_input(
                "Total Farm Area (Acres)",
                min_value=0.1,
                max_value=1000.0,
                value=float(st.session_state.get("farm_area_acres", 1.0)),
                step=0.25,
                format="%.2f",
                help="Enter total farmland area in acres. Supports decimal values like 0.5, 1.2, 2.5, 10.0.",
            )
            st.session_state["farm_area_acres"] = farm_area

            # Selected Location Card
            st.markdown("#### 📌 Active Farm Coordinates")
            if st.session_state.get("has_user_selected"):
                rev = get_location_from_coordinates(
                    st.session_state["selected_lat"], st.session_state["selected_lon"]
                )
                place_display = rev.get("location_name", "Farmland Point") if rev else "Farmland Point"
                st.markdown(
                    f"""
                    <div class="selection-card">
                        <div style="font-size: 1.05rem; font-weight: 700; color: #163a2d; margin-bottom: 4px;">
                            📍 {place_display}
                        </div>
                        <div style="font-size: 0.88rem; color: #20322b;">
                            <b>Latitude:</b> {st.session_state['selected_lat']:.4f}°<br>
                            <b>Longitude:</b> {st.session_state['selected_lon']:.4f}°<br>
                            <b>Farm Area:</b> {farm_area} Acre{'s' if farm_area != 1 else ''}
                        </div>
                    </div>
                    """,
                    unsafe_allow_html=True,
                )
            else:
                st.info("👈 Click on the India map or use GPS to set farm location.")

            # Stage 1 Button: Analyze Farm
            analyze_clicked = st.button(
                "🔍 Analyze Farm",
                type="primary",
                use_container_width=True,
                disabled=not st.session_state.get("has_user_selected"),
            )

    with map_col:
        # Determine center and zoom
        if st.session_state.get("has_user_selected"):
            center_coords = [st.session_state["selected_lat"], st.session_state["selected_lon"]]
            zoom_level = 9
        else:
            center_coords = [INDIA_LAT, INDIA_LON]
            zoom_level = INDIA_ZOOM

        # Create Folium Map
        m = folium.Map(
            location=center_coords,
            zoom_start=zoom_level,
            tiles="OpenStreetMap",
            control_scale=True,
        )

        # If user has pinned a point, add marker
        if st.session_state.get("has_user_selected"):
            folium.Marker(
                location=[st.session_state["selected_lat"], st.session_state["selected_lon"]],
                popup=folium.Popup(
                    f"<b>Farmland Location</b><br>Lat: {st.session_state['selected_lat']:.4f}<br>Lon: {st.session_state['selected_lon']:.4f}<br>Area: {farm_area} Acres",
                    max_width=250,
                ),
                tooltip="Selected Farm Location",
                icon=folium.Icon(color="green", icon="leaf", prefix="fa"),
            ).add_to(m)

        # Render Folium Map in Streamlit with click capturing
        map_output = st_folium(
            m,
            width="100%",
            height=460,
            returned_objects=["last_clicked"],
            key="india_folium_map",
        )

        # Process map click event directly into st.session_state
        if map_output and map_output.get("last_clicked"):
            clicked = map_output["last_clicked"]
            c_lat = float(clicked["lat"])
            c_lon = float(clicked["lng"])
            if (
                not st.session_state.get("has_user_selected")
                or abs(c_lat - st.session_state["selected_lat"]) > 0.0001
                or abs(c_lon - st.session_state["selected_lon"]) > 0.0001
            ):
                st.session_state["selected_lat"] = c_lat
                st.session_state["selected_lon"] = c_lon
                st.session_state["has_user_selected"] = True
                # Reset previous plans on location change
                st.session_state["analysis_results"] = None
                st.session_state["selected_crop"] = None
                st.session_state["farm_plan"] = None
                st.rerun()

    # Handle "Analyze Farm" Action (Stage 1 Only)
    if analyze_clicked:
        with st.spinner("Stage 1: Analyzing weather telemetry, soil properties, NPK nutrients & scoring top crops..."):
            try:
                stage1_res = analyze_farm(
                    latitude=st.session_state["selected_lat"],
                    longitude=st.session_state["selected_lon"],
                    farm_area_acres=farm_area,
                )
                st.session_state["analysis_results"] = stage1_res
                st.session_state["top_3_crops"] = stage1_res.get("top_3_crops", [])
                st.session_state["selected_crop"] = None
                st.session_state["farm_plan"] = None
            except Exception as exc:
                st.error(f"Farm analysis failed: {exc}")
                st.session_state["analysis_results"] = None

    # Render Stage 1 Results if Available
    stage1_data = st.session_state.get("analysis_results")
    if stage1_data:
        st.markdown("---")
        _render_environment_overview(stage1_data)
        _render_stage1_crop_cards(
            stage1_data.get("top_3_crops", []),
            farm_area=float(st.session_state.get("farm_area_acres", 1.0)),
        )

    # Render Stage 2 Detailed Plan if a crop has been selected
    stage2_plan = st.session_state.get("farm_plan")
    if stage2_plan:
        _render_stage2_detailed_plan(
            stage2_plan,
            farm_area=float(st.session_state.get("farm_area_acres", 1.0)),
        )
    elif not stage1_data:
        st.info("👆 Pinned your farmland location on the map, choose your farm acreage, and click **'🔍 Analyze Farm'** to view the Top 3 crop candidates.")


if __name__ == "__main__":
    main()
