import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import urllib.parse
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

st.set_page_config(page_title="BSF Environment Dashboard", layout="wide")

# --- Get credentials from Streamlit secrets ---
db_secrets = st.secrets.get("database", {})
user = db_secrets.get("user")
password = db_secrets.get("password")
host = db_secrets.get("host", "cluster0.yrpctoh.mongodb.net")  # default if not set

if not user or not password:
    st.error("Database credentials missing")
    st.stop()

# --- URL-encode credentials for MongoDB URI ---
encoded_username = urllib.parse.quote_plus(user)
encoded_password = urllib.parse.quote_plus(password)

mongo_uri = f"mongodb+srv://{encoded_username}:{encoded_password}@{host}"

# --- Streamlit page settings ---
st.title("Real-Time Environment Control Data Dashboard")

# --- Data processing helpers ---------------------------------------------

# Columns that identify a record rather than measure something.
ID_COLUMNS = {"_id", "ts", "uid", "env_id", "env_type"}

# Known short field codes get a friendlier display name; anything else is
# title-cased from its raw field name (e.g. "atomizer" -> "Atomizer").
FRIENDLY_NAMES = {"t": "Temperature (°C)", "h": "Humidity (%)"}

STALE_AFTER = timedelta(minutes=30)

# Fixed palette so a cage always gets the same color everywhere (charts and
# the floating legend), regardless of filtering or trace order.
CAGE_COLOR_SEQUENCE = px.colors.qualitative.Plotly


def display_name(col):
    return FRIENDLY_NAMES.get(col, col.replace("_", " ").title())


def hex_to_rgba(hex_color, alpha):
    hex_color = hex_color.lstrip("#")
    r, g, b = (int(hex_color[i:i + 2], 16) for i in (0, 2, 4))
    return f"rgba({r},{g},{b},{alpha})"


def detect_column_types(df):
    """Split measurement columns into on/off (boolean) and continuous (numeric).

    Boolean detection is value-based, not just dtype, since a field missing on
    some records (e.g. only present for certain env_types) ends up as an
    object column of True/False/NaN. Any column holding non-scalar values
    (lists/dicts occasionally sent by device firmware) is skipped rather than
    hashed, since Series.unique() raises on unhashable values.
    """
    bool_cols, numeric_cols, skipped_cols = [], [], []
    for col in df.columns:
        if col in ID_COLUMNS:
            continue
        series = df[col].dropna()
        if series.empty:
            continue
        if series.apply(lambda v: isinstance(v, (list, dict, set))).any():
            skipped_cols.append(col)
            continue
        try:
            unique_vals = set(series.unique().tolist())
        except TypeError:
            skipped_cols.append(col)
            continue
        if unique_vals.issubset({True, False}):
            bool_cols.append(col)
        elif pd.api.types.is_numeric_dtype(series):
            numeric_cols.append(col)
        else:
            skipped_cols.append(col)
    return bool_cols, numeric_cols, skipped_cols


def normalize_df(df, bool_cols=()):
    if "ts" in df.columns:
        df["ts"] = pd.to_datetime(df["ts"], unit="s")
    if "_id" in df.columns:
        df["_id"] = df["_id"].astype(str)
    if "env_id" in df.columns:
        df["env_id"] = df["env_id"].astype(str)
    for col in bool_cols:
        if col in df.columns:
            df[col] = df[col].astype(float)
    return df


def aggregate_dataframe(df, freq, group_cols, bool_cols, numeric_cols):
    """Resample to fixed-size time buckets.

    Continuous variables become a period average; on/off variables become a
    duty-cycle percentage (share of readings that were True in that period).
    """
    agg = {col: "mean" for col in (numeric_cols + bool_cols)}
    grouped = (
        df.groupby(group_cols + [pd.Grouper(key="ts", freq=freq)])
        .agg(agg)
        .reset_index()
    )
    for col in bool_cols:
        grouped[col] = grouped[col] * 100
    return grouped


def smooth_dataframe(df, window, group_cols, value_cols):
    """Apply a centered rolling mean per sensor to flatten out noisy oscillation."""
    if window <= 1 or not value_cols:
        return df
    df = df.sort_values("ts").copy()
    rolling = lambda s: s.rolling(window, min_periods=1, center=True).mean()
    if group_cols:
        df[value_cols] = df.groupby(group_cols)[value_cols].transform(rolling)
    else:
        df[value_cols] = df[value_cols].apply(rolling)
    return df


def metric_label(col, is_bool, resolution):
    label = display_name(col)
    if not is_bool:
        return label
    return f"{label} (On/Off)" if resolution == "Raw" else f"{label} Duty Cycle (%)"


def format_age(td):
    total_min = int(td.total_seconds() // 60)
    if total_min < 60:
        return f"{max(total_min, 0)} min ago"
    hours, minutes = divmod(total_min, 60)
    return f"{hours}h {minutes}m ago"


# --- Cached MongoDB access -------------------------------------------------
# Widget interactions (mode, filters, smoothing) trigger a full script rerun
# in Streamlit, so without caching every click would re-hit the database.

@st.cache_resource(show_spinner=False)
def get_client(uri):
    return MongoClient(uri, server_api=ServerApi('1'))


@st.cache_data(ttl=300, show_spinner="Loading sensor data...")
def fetch_records(_client, start_ts, end_ts):
    query = {"ts": {"$gte": start_ts, "$lte": end_ts}}
    docs = list(_client.devices["records"].find(query))
    return pd.DataFrame(docs)


@st.cache_data(ttl=60, show_spinner="Checking latest readings...")
def fetch_latest_by_cage(_client):
    pipeline = [
        {"$sort": {"ts": -1}},
        {"$group": {"_id": "$env_id", "doc": {"$first": "$$ROOT"}}},
    ]
    docs = [d["doc"] for d in _client.devices["records"].aggregate(pipeline)]
    return pd.DataFrame(docs)


@st.cache_data(ttl=60, show_spinner="Checking latest readings...")
def fetch_latest_single(_client):
    docs = list(_client.devices["records"].find().sort("ts", -1).limit(1))
    return pd.DataFrame(docs)


try:
    client = get_client(mongo_uri)

    # --- Sidebar: Time Range ---
    st.sidebar.header("📅 Time Range")
    quick_range = st.sidebar.selectbox(
        "Quick range",
        ["Last 24 hours", "Last 3 days", "Last 7 days", "Last 30 days", "Custom range"],
        index=2,
    )

    if quick_range == "Custom range":
        today = datetime.now().date()
        start_date, end_date = st.sidebar.date_input(
            "Select custom date range",
            value=[today - timedelta(days=7), today],
            min_value=today - timedelta(days=365),
            max_value=today,
        )
        if isinstance(start_date, list):
            start_date, end_date = start_date[0], start_date[1]
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())
    else:
        # Round "now" to the minute so repeated reruns within that minute
        # reuse the same cache entry instead of refetching every widget click.
        days_map = {"Last 24 hours": 1, "Last 3 days": 3, "Last 7 days": 7, "Last 30 days": 30}
        end_dt = datetime.now().replace(second=0, microsecond=0)
        start_dt = end_dt - timedelta(days=days_map[quick_range])

    df = fetch_records(client, start_dt.timestamp(), end_dt.timestamp())
    df = normalize_df(df)

    if df.empty:
        st.warning("No data available for the selected time range.")
        st.stop()

    bool_cols, numeric_cols, skipped_cols = detect_column_types(df)
    df = normalize_df(df, bool_cols)  # cast True/False/NaN -> 1.0/0.0/NaN for aggregation & smoothing
    if skipped_cols:
        st.sidebar.caption(f"Ignoring unsupported columns: {', '.join(skipped_cols)}")

    group_cols = [c for c in ("env_id",) if c in df.columns]
    metric_cols = numeric_cols + bool_cols

    # --- Sidebar: Cage filter ---
    cage_colors = {}
    if group_cols:
        st.sidebar.header("🏠 Cages")
        all_cages = sorted(df["env_id"].unique().tolist())
        cage_colors = {
            cage: CAGE_COLOR_SEQUENCE[i % len(CAGE_COLOR_SEQUENCE)]
            for i, cage in enumerate(all_cages)
        }
        selected_cages = st.sidebar.multiselect("Show cages", all_cages, default=all_cages)
        if not selected_cages:
            st.warning("Select at least one cage in the sidebar.")
            st.stop()
        df = df[df["env_id"].isin(selected_cages)]

    # --- Sidebar: Variable filter ---
    st.sidebar.header("🔬 Variables")
    selected_metrics = st.sidebar.multiselect(
        "Show variables",
        metric_cols,
        default=metric_cols,
        format_func=lambda c: display_name(c),
    )
    if not selected_metrics:
        st.warning("Select at least one variable in the sidebar.")
        st.stop()

    # --- Sidebar: Analysis mode ---
    st.sidebar.header("📈 Analysis Mode")
    mode = st.sidebar.radio(
        "What do you want to look at?",
        ["General Analysis", "Last Update", "Compare Variables"],
        help=(
            "General Analysis: trends over time for every selected variable.\n"
            "Last Update: current snapshot per cage, with a staleness check.\n"
            "Compare Variables: correlate any two variables against each other."
        ),
    )

    resolution, smoothing_window = "Raw", 1
    if mode != "Last Update":
        resolution = st.sidebar.radio(
            "Time resolution",
            ["Raw", "15-min average", "Hourly average", "Daily average"],
            index=2,
            help=(
                "Aggregating reduces sensor noise. On/off equipment fields "
                "(e.g. fans, heaters) are converted into a duty-cycle percentage "
                "— the share of that period the equipment was on."
            ),
        )
        smoothness = st.sidebar.select_slider(
            "Smoothness",
            options=["Off", "Light", "Medium", "Strong"],
            value="Off",
            help="Averages each point with its neighbors to flatten out oscillation and make trends easier to read.",
        )
        smoothing_window = {"Off": 1, "Light": 3, "Medium": 5, "Strong": 9}[smoothness]

    freq_map = {"15-min average": "15min", "Hourly average": "h", "Daily average": "D"}
    period_label = {
        "Raw": "readings", "15-min average": "15-min periods",
        "Hourly average": "hours", "Daily average": "days",
    }
    bool_selected = [c for c in bool_cols if c in selected_metrics]
    numeric_selected = [c for c in numeric_cols if c in selected_metrics]

    if resolution in freq_map:
        plot_df = aggregate_dataframe(df, freq_map[resolution], group_cols, bool_cols, numeric_cols)
    else:
        plot_df = df.copy()
    plot_df = smooth_dataframe(plot_df, smoothing_window, group_cols, metric_cols)

    color_arg = "env_id" if group_cols else None

    # =====================================================================
    # General Analysis: every selected variable over time, one facet row each
    # =====================================================================
    if mode == "General Analysis":
        st.subheader("📊 Sensor Readings Over Time" + (" by Cage" if color_arg else ""))

        if group_cols:
            # st.markdown renders straight into the page (unlike st.html, which
            # sandboxes content in its own small iframe and breaks position:fixed/
            # sticky since it has no awareness of the real page's scroll). Real
            # position:sticky here means it sits in place until the user scrolls
            # past it, then sticks to the top of the viewport.
            legend_rows = "".join(
                f'<div style="display:flex;align-items:center;gap:10px;padding:8px 12px;'
                f'margin-bottom:6px;background:{hex_to_rgba(cage_colors[c], 0.18)};'
                f'border-left:5px solid {cage_colors[c]};border-radius:6px;">'
                f'<span style="font-size:15px;">Cage {c}</span></div>'
                for c in selected_cages
            )
            st.markdown(
                f"""
                <style>
                .cage-legend-sticky {{
                    position: sticky; top: 55px; z-index: 999;
                    width: fit-content; margin: 0 0 16px auto;
                    background: var(--secondary-background-color, #f0f2f6);
                    border: 1px solid rgba(128,128,128,0.35); border-radius: 10px;
                    padding: 12px 14px; box-shadow: 0 2px 10px rgba(0,0,0,0.15);
                }}
                </style>
                <div class="cage-legend-sticky">
                    <div style="font-weight:700;font-size:14px;margin-bottom:8px;
                                text-transform:uppercase;letter-spacing:0.03em;">Cages</div>
                    {legend_rows}
                </div>
                """,
                unsafe_allow_html=True,
            )

        shown_metrics = numeric_selected + bool_selected
        labels = {col: metric_label(col, col in bool_cols, resolution) for col in shown_metrics}
        df_long = plot_df.melt(
            id_vars=["ts"] + group_cols,
            value_vars=shown_metrics,
            var_name="metric",
            value_name="value",
        )
        df_long["metric"] = df_long["metric"].map(labels)

        fig_all = px.line(
            df_long, x="ts", y="value", color=color_arg, facet_row="metric",
            color_discrete_map=cage_colors or None,
            title="Sensor Readings Over Time" + (f" ({resolution})" if resolution != "Raw" else ""),
            labels={"ts": "Timestamp", "value": "Value", "env_id": "Cage"},
        )
        fig_all.update_yaxes(matches=None)
        fig_all.update_xaxes(showticklabels=True, tickformat="%b %d<br>%H:%M")
        fig_all.for_each_annotation(lambda a: a.update(text=a.text.split("=", 1)[-1]))
        fig_all.update_layout(
            height=max(320, 250 * len(shown_metrics)),
            margin=dict(b=60),
            hovermode="x unified",
            legend_title_text="Cage" if color_arg else None,
            legend=dict(font=dict(size=13)),
        )
        st.plotly_chart(fig_all, use_container_width=True)

        st.subheader("📋 Summary Statistics")
        summary_rows = []
        for col in numeric_selected:
            summary_rows.append({
                "Variable": display_name(col), "Mean": plot_df[col].mean(),
                "Min": plot_df[col].min(), "Max": plot_df[col].max(), "Std Dev": plot_df[col].std(),
            })
        for col in bool_selected:
            summary_rows.append({
                "Variable": metric_label(col, True, resolution), "Mean": plot_df[col].mean(),
                "Min": plot_df[col].min(), "Max": plot_df[col].max(), "Std Dev": plot_df[col].std(),
            })
        if summary_rows:
            st.dataframe(pd.DataFrame(summary_rows).round(2), use_container_width=True)

        st.download_button(
            "⬇️ Download processed data (CSV)",
            plot_df.to_csv(index=False).encode("utf-8"),
            file_name=f"bsf_data_{resolution.lower().replace(' ', '_')}.csv",
            mime="text/csv",
        )

        with st.expander("Raw data"):
            st.dataframe(df, use_container_width=True)
        with st.expander("Processed data"):
            st.dataframe(plot_df, use_container_width=True)

    # =====================================================================
    # Last Update: current snapshot per cage, with a staleness check
    # =====================================================================
    elif mode == "Last Update":
        st.subheader("📍 Most Recent Readings")
        scope = st.radio(
            "Show the latest reading from:",
            ["Selected time range", "All time"],
            horizontal=True,
            help='"All time" checks the single most recent reading ever recorded per cage, ignoring the time range in the sidebar.',
        )
        now = datetime.now()

        if scope == "All time":
            if group_cols:
                latest = normalize_df(fetch_latest_by_cage(client), bool_cols)
                latest = latest.sort_values("env_id") if "env_id" in latest.columns else latest
            else:
                latest = normalize_df(fetch_latest_single(client), bool_cols)
        else:
            if group_cols:
                latest = df.sort_values("ts").groupby("env_id").tail(1).sort_values("env_id")
            else:
                latest = df.sort_values("ts").tail(1)

        if latest.empty:
            st.info("No readings available yet.")
        else:
            stale_count = 0
            cols = st.columns(len(latest))
            for panel, (_, row) in zip(cols, latest.iterrows()):
                cage_id = row.get("env_id") if group_cols else None
                accent = cage_colors.get(cage_id, "#888888") if group_cols else "#888888"
                age = now - row["ts"].to_pydatetime()
                is_stale = age > STALE_AFTER
                stale_count += is_stale
                with panel, st.container(border=True):
                    st.markdown(
                        f'<div style="border-left:5px solid {accent};padding-left:8px;">'
                        f'<span style="font-weight:700;font-size:15px;">'
                        f'{"Cage " + cage_id if cage_id else "Sensor"}</span></div>',
                        unsafe_allow_html=True,
                    )
                    st.caption(("🔴 " if is_stale else "🟢 ") + format_age(age))
                    if is_stale:
                        st.warning(f"No new data in over {int(STALE_AFTER.total_seconds() // 60)} min")
                    for col in numeric_selected:
                        st.metric(display_name(col), f"{row[col]:.1f}")
                    badge_html = ""
                    for col in bool_selected:
                        if col not in row.index or pd.isna(row[col]):
                            bg, text = "#9e9e9e", "N/A"
                        elif row[col]:
                            bg, text = "#1a7f37", "ON"
                        else:
                            bg, text = "#6e7781", "OFF"
                        badge_html += (
                            f'<span style="display:inline-block;background:{bg};color:white;'
                            f'padding:3px 10px;border-radius:12px;font-size:12px;font-weight:600;'
                            f'margin:2px 4px 0 0;">{display_name(col)}: {text}</span>'
                        )
                    if badge_html:
                        st.markdown(badge_html, unsafe_allow_html=True)

            if stale_count:
                st.warning(f"⚠️ {stale_count} of {len(latest)} cage(s) haven't reported in over {int(STALE_AFTER.total_seconds() // 60)} minutes.")
            else:
                st.success("✅ All cages reporting recently.")

        st.caption(
            "Showing the most recent reading within the selected time range above."
            if scope == "Selected time range" else
            "Showing the single most recent reading ever recorded, regardless of the sidebar time range."
        )

    # =====================================================================
    # Compare Variables: correlation heatmap + a focused pair scatter
    # =====================================================================
    else:
        st.subheader("🔗 Correlation Between Variables")
        corr_cols = numeric_selected + bool_selected
        if len(corr_cols) >= 2:
            corr_labels = {col: metric_label(col, col in bool_cols, resolution) for col in corr_cols}
            corr = plot_df[corr_cols].rename(columns=corr_labels).corr()
            fig_corr = px.imshow(
                corr, text_auto=".2f", color_continuous_scale="RdBu_r", zmin=-1, zmax=1,
                title="Correlation Matrix (Pearson r)",
            )
            st.plotly_chart(fig_corr, use_container_width=True)
        else:
            st.info("Select at least two variables in the sidebar to see correlations.")

        st.subheader("🔎 Compare a Pair of Variables")
        pick_col1, pick_col2 = st.columns(2)
        default_x = "t" if "t" in selected_metrics else selected_metrics[0]
        default_y = "h" if "h" in selected_metrics else selected_metrics[-1]
        with pick_col1:
            x_var = st.selectbox("Variable X", selected_metrics, index=selected_metrics.index(default_x), format_func=display_name)
        with pick_col2:
            y_var = st.selectbox("Variable Y", selected_metrics, index=selected_metrics.index(default_y), format_func=display_name)

        fig_scatter = px.scatter(
            plot_df, x=x_var, y=y_var, color=color_arg,
            color_discrete_map=cage_colors or None,
            title=f"{display_name(x_var)} vs {display_name(y_var)}",
            labels={x_var: metric_label(x_var, x_var in bool_cols, resolution), y_var: metric_label(y_var, y_var in bool_cols, resolution), "env_id": "Cage"},
        )
        st.plotly_chart(fig_scatter, use_container_width=True)

        pair_corr = plot_df[[x_var, y_var]].corr().iloc[0, 1]
        if pd.isna(pair_corr):
            st.info("Not enough overlapping data to compute a correlation.")
        else:
            st.metric("Correlation (Pearson r)", f"{pair_corr:.2f}")

except ConnectionFailure as e:
    st.error(f"MongoDB connection failed: {e}")
except Exception as e:
    st.error(f"An error occurred: {e}")
