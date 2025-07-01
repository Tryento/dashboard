import streamlit as st
import pandas as pd
from datetime import date, timedelta
from abc import ABC, abstractmethod
from dotenv import load_dotenv, find_dotenv
_ = load_dotenv(find_dotenv()) # read local .env file

from src.classes.remote_db import RemoteDB

# --- Data handling with caching ---
class DataFetcher:
    @staticmethod
    def fetch(start_date: date, end_date: date) -> pd.DataFrame:
        # Replace with real data source logic
        rng = pd.date_range(start=start_date, end=end_date, freq='D')
        return pd.DataFrame({
            'date': rng,
            'value': (pd.Series(range(len(rng))) * 5).astype(int)
        })

# --- Abstract sidebar component ---
class ISidebarComponent(ABC):
    """
    Abstract base class for sidebar UI components.
    """
    @abstractmethod
    def render(self):
        """
        Render the component in the sidebar and return its output.
        """
        pass

# --- Date filter implementation ---
class DateFilter(ISidebarComponent):
    def __init__(self, label: str, key: str, default: date):
        self.label = label
        self.key = key
        self.default = default
        self.date = None

    def render(self) -> date:
        self.date = st.sidebar.date_input(
            self.label,
            value=self.default,
            key=self.key
        )
        return self.date

class FromDateFilter(DateFilter):
    def __init__(self, default: date):
        super().__init__("From", "from_date", default)

class ToDateFilter(DateFilter):
    def __init__(self, default: date):
        super().__init__("To", "to_date", default)

# --- Fetch button component ---
class FetchButton(ISidebarComponent):
    def __init__(self, label: str = "Fetch Data"):
        self.label = label

    def render(self) -> bool:
        return st.sidebar.button(self.label)

# --- Sidebar assembly ---
class SidebarNav:
    def __init__(self, from_default: date, to_default: date):
        self.header = st.sidebar.header("Filter Dates")
        self.components = {
            'from_filter': FromDateFilter(from_default),
            'to_filter': ToDateFilter(to_default),
            'fetch_button': FetchButton()
        }

    def render(self):
        return self.header, self.components["from_filter"].render(), self.components["to_filter"].render(), self.components["fetch_button"].render()

# --- Main dashboard display ---
class Dashboard:
    def __init__(self, start_date: date, end_date: date):
        self.start = start_date
        self.end = end_date

    def render(self):
        if self.start > self.end:
            st.sidebar.error("Error: 'From' date must be before 'To' date.")
            st.stop()

        st.header(f"Data from {self.start.isoformat()} to {self.end.isoformat()}")
        data = RemoteDB()
        data.connect()
        df = pd.DataFrame()
        if data.connected:
            st.sidebar.success("Connected to database")
            docs = data.fetch_records(self.start, self.end)
            df = pd.DataFrame(docs)
            st.dataframe(df)

        csv = df.to_csv(index=False).encode('utf-8')
        st.download_button(
            label="Download data as CSV",
            data=csv,
            file_name=f"data_{self.start}_{self.end}.csv",
            mime='text/csv'
        )

# --- Orchestrator for the Streamlit app ---
class StreamlitApp:
    def __init__(self):
        st.set_page_config(page_title="Date Filter Example", layout="centered")
        # Initialize session state
        if 'from_date' not in st.session_state:
            st.session_state.from_date = date.today() - timedelta(days=7)
        if 'to_date' not in st.session_state:
            st.session_state.to_date = date.today()

    def run(self):
        sidebar = SidebarNav(
            from_default=st.session_state.from_date,
            to_default=st.session_state.to_date
        )
        header, start, end, should_fetch = sidebar.render()

        if should_fetch:
            dashboard = Dashboard(start, end)
            dashboard.render()
        else:
            st.sidebar.info("Click 'Fetch Data' to load data")

if __name__ == "__main__":
    app = StreamlitApp()
    app.run()

