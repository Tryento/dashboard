import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import os
import urllib.parse
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi
from dotenv import load_dotenv

# --- Load .env locally only ---
if os.path.exists(".env"):
    load_dotenv()

# --- Get MongoDB credentials ---
def get_secret(key):
    # First try Streamlit secrets
    if "database" in st.secrets:
        val = st.secrets["database"].get(key)
        if val:
            return val
    # Fallback to environment variable
    return os.getenv(key)

user = get_secret("user")
password = get_secret("password")
host = get_secret("host") or "cluster0.yrpctoh.mongodb.net"

# Check credentials
if not user or not password:
    st.error("Database credentials missing. Make sure to set them in `.env` locally or in Streamlit secrets.")
    st.stop()

# URL-encode credentials
encoded_username = urllib.parse.quote_plus(str(user))
encoded_password = urllib.parse.quote_plus(str(password))

# MongoDB connection URI
mongo_uri = f"mongodb+srv://{encoded_username}:{encoded_password}@{host}/?retryWrites=true&w=majority&appName=Cluster0"

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

    if isinstance(start_date, list):
        start_dt = datetime.combine(start_date[0], datetime.min.time())
        end_dt = datetime.combine(start_date[1], datetime.max.time())
    else:
        start_dt = datetime.combine(start_date, datetime.min.time())
        end_dt = datetime.combine(end_date, datetime.max.time())

    # --- Query MongoDB ---
    query = {"ts": {"$gte": start_dt.timestamp(), "$lte": end_dt.timestamp()}}
    documents = list(collection.find(query))
    df = pd.DataFrame(documents)

    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'], unit='s')
    if '_id' in df.columns:
        df['_id'] = df['_id'].astype(str)

    # --- Display ---
    if not df.empty:
        st.write("#### Data", df)

        if df.isnull().values.any():
            st.warning("Some data has missing or null values.")

        st.subheader("Temperature vs Humidity")
        st.plotly_chart(px.scatter(df, x='t', y='h', title="Temperature vs Humidity"))

        st.subheader("Temperature over Time")
        st.plotly_chart(px.line(df, x='ts', y='t', title="Temperature over Time"))

        st.subheader("Humidity over Time")
        st.plotly_chart(px.line(df, x='ts', y='h', title="Humidity over Time"))

        if 'env_id' in df.columns:
            st.subheader("🔥 Temperature History by Cage")
            st.plotly_chart(
                px.line(df, x="ts", y="t", color="env_id",
                        title="Temperature Over Time per Cage",
                        labels={"ts": "Timestamp", "t": "Temperature (°C)", "env_id": "Cage"}),
                use_container_width=True
            )

            st.subheader("💦 Humidity History by Cage")
            st.plotly_chart(
                px.line(df, x="ts", y="h", color="env_id",
                        title="Humidity Over Time per Cage",
                        labels={"ts": "Timestamp", "h": "Humidity (%)", "env_id": "Cage"}),
                use_container_width=True
            )
        else:
            st.warning("No 'env_id' column found. Cannot display per cage analysis.")
    else:
        st.warning("No data available for the selected date range.")

except ConnectionFailure as e:
    st.error(f"MongoDB connection failed: {e}")
except Exception as e:
    st.error(f"An error occurred: {e}")