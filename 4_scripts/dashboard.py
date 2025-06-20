import streamlit as st
import pandas as pd
import plotly.express as px
from datetime import datetime, timedelta
import configparser
import os
import urllib.parse
from pymongo import MongoClient
from pymongo.errors import ConnectionFailure
from pymongo.server_api import ServerApi

current_path = os.getcwd()
os.chdir(os.path.dirname(current_path))
project_path = os.getcwd()
input_data = os.path.join(project_path, "2_data", "in")
output_data = os.path.join(project_path, "2_data", "out")
print(input_data)
print(output_data)

config = configparser.ConfigParser()
config.read(os.path.join(project_path, 'conf', 'conf.ini'))

# MongoDB Credentials
user = config.get("mongodb", "user", raw=True)
password = config.get("mongodb", "password", raw=True)

# URL-encode the password
encoded_username = urllib.parse.quote_plus(user)
encoded_password = urllib.parse.quote_plus(password)

# MongoDB connection URI
mongo_uri = f"mongodb+srv://{encoded_username}:{encoded_password}@cluster0.yrpctoh.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"

# Streamlit page settings
st.title("Real-Time Environment Control Data Dashboard")

try:
    # Connect to MongoDB
    client = MongoClient(mongo_uri, server_api=ServerApi('1'))
    
    # Access the database and collection
    db = client.devices
    collection = db["records"]
    
    # Fetch all documents from the "records" collection
    documents = list(collection.find({}))

    # Convert MongoDB data into a pandas DataFrame
    df = pd.DataFrame(documents)
    
   # Ensure 'ts' column is in datetime format
    if 'ts' in df.columns:
        df['ts'] = pd.to_datetime(df['ts'], errors='coerce')

    # Get the last 5 days from today
    last_5_days = datetime.now() - timedelta(days=5)

    # Filter DataFrame
    df = df[df['ts'] >= last_5_days]

    # Convert '_id' column to string
    if '_id' in df.columns:
        df['_id'] = df['_id'].astype(str)


    if not df.empty:
        # Display data in table format on Streamlit
        st.write("#### Data", df)

        # Check for missing or null values
        if df.isnull().values.any():
            st.warning("Some data has missing or null values.")
        
        # Plotting
        st.subheader("Temperature vs Humidity")
        fig = px.scatter(df, x='t', y='h', title="Temperature vs Humidity")
        st.plotly_chart(fig)

        st.subheader("Temperature over Time")
        fig = px.line(df, x='ts', y='t', title="Temperature over Time")
        st.plotly_chart(fig)

        st.subheader("Humidity over Time")
        fig = px.line(df, x='ts', y='h', title="Humidity over Time")
        st.plotly_chart(fig)
        
        # Per Cage Analysis**
        if 'env_id' in df.columns:
            st.subheader("🔥 Temperature History by Cage")
            fig_temp = px.line(df, x="ts", y="t", color="env_id",
                               title="Temperature Over Time per Cage",
                               labels={"ts": "Timestamp", "t": "Temperature (°C)", "env_id": "Cage"})
            st.plotly_chart(fig_temp, use_container_width=True)

            st.subheader("💦 Humidity History by Cage")
            fig_humidity = px.line(df, x="ts", y="h", color="env_id",
                                   title="Humidity Over Time per Cage",
                                   labels={"ts": "Timestamp", "h": "Humidity (%)", "env_id": "Cage"})
            st.plotly_chart(fig_humidity, use_container_width=True)
        else:
            st.warning("No 'env_id' column found. Cannot display per cage analysis.")

    else:
        st.write("No data available.")

except ConnectionFailure as e:
    st.error(f"MongoDB connection failed: {e}")
except Exception as e:
    st.error(f"An error occurred: {e}")
