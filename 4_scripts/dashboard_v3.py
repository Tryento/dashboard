import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import urllib.parse
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

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

try:
    # Connect to MongoDB
    client = MongoClient(mongo_uri, server_api=ServerApi('1'))
    db = client.devices
    collection = db["records"]

    # --- Sidebar Date Filter ---
    st.sidebar.header("📅 Date Filter")
    default_end = datetime.now().date()
    default_start = default_end - timedelta(days=5)

    start_date, end_date = st.sidebar.date_input(
        "Select date range",
        value=[default_start, default_end],
        min_value=default_start - timedelta(days=365),
        max_value=default_end
    )

    # Ensure proper datetime objects
    if isinstance(start_date, list):
        start_dt = datetime.combine(start_date[0], datetime.min.time())
        end_dt = datetime.combine(start_date[1], datetime.max.time())
    else:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

    # --- Query MongoDB with date range ---
    query = {"ts": {"$gte": start_dt.timestamp(), "$lte": end_dt.timestamp()}}
    documents = list(collection.find(query))

    # Convert to DataFrame
    df = pd.DataFrame(documents)

    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'], unit='s')
    if '_id' in df.columns:
        df['_id'] = df['_id'].astype(str)

    # --- Display and Plot ---
    if not df.empty:
        st.write("#### Data", df)

        if df.isnull().values.any():
            st.warning("Some data has missing or null values.")

        st.subheader("Temperature vs Humidity")
        fig = px.scatter(df, x='t', y='h', title="Temperature vs Humidity")
        st.plotly_chart(fig)

        st.subheader("Temperature over Time")
        fig = px.line(df, x='ts', y='t', title="Temperature over Time")
        st.plotly_chart(fig)

        st.subheader("Humidity over Time")
        fig = px.line(df, x='ts', y='h', title="Humidity over Time")
        st.plotly_chart(fig)

        # Per Cage Analysis
        if 'env_id' in df.columns:
            st.subheader("🔥 Temperature History by Cage")
            fig_temp = px.line(
                df, x="ts", y="t", color="env_id",
                title="Temperature Over Time per Cage",
                labels={"ts": "Timestamp", "t": "Temperature (°C)", "env_id": "Cage"}
            )
            st.plotly_chart(fig_temp, use_container_width=True)

            st.subheader("💦 Humidity History by Cage")
            fig_humidity = px.line(
                df, x="ts", y="h", color="env_id",
                title="Humidity Over Time per Cage",
                labels={"ts": "Timestamp", "h": "Humidity (%)", "env_id": "Cage"}
            )
            st.plotly_chart(fig_humidity, use_container_width=True)
        else:
            st.warning("No 'env_id' column found. Cannot display per cage analysis.")
    else:
        st.warning("No data available for the selected date range.")

except ConnectionFailure as e:
    st.error(f"MongoDB connection failed: {e}")
except Exception as e:
    st.error(f"An error occurred: {e}")