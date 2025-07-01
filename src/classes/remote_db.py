import os
import sys
import urllib
from typing import Any, Dict
from abc import ABC, abstractmethod
from pymongo.server_api import ServerApi
from dotenv import load_dotenv, find_dotenv
from pymongo.mongo_client import MongoClient
import logging


project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..', '..'))
sys.path.insert(0, project_root)


_ = load_dotenv(find_dotenv()) # read local .env file

class IDatabase(ABC):
    @abstractmethod
    def connect(self) -> None:
        pass
    
    @abstractmethod
    def disconnect(self) -> None:
        pass
    
    @abstractmethod
    def send_data(self, data: Dict[str, Any]) -> bool:
        pass
    

class RemoteDB(IDatabase):
    def __init__(self):
        self._initialized: bool = False
        self.connected: bool = False
        self.client = None
        self.db = None
        self.coll = None
        self.encoded_username = urllib.parse.quote_plus(os.getenv("username"), "tryento")
        self.encoded_password = urllib.parse.quote_plus(os.getenv("password"))
        self.DB_URL=f"mongodb+srv://{self.encoded_username}:{self.encoded_password}@cluster0.yrpctoh.mongodb.net/?retryWrites=true&w=majority&appName=Cluster0"
  

    def connect(self):
        try:
            self.client = MongoClient(self.DB_URL, server_api=ServerApi('1'))
            self.db = self.client.devices
            self.coll = self.db.records
            self.client.admin.command('ping')
            logging.info("Connected to MongoDB")
        except Exception as e:
            logging.error(f"Could not connect to MongoDB: {e}")
            self.connected = False
            return
        self._initialized = True
        self.connected = True


    def disconnect(self):
        if self._initialized and self.client is not None:
            self.client.close()
            logging.info("Disconnected from MongoDB")
    
    def send_data(self, data: dict):
        if self.coll.insert_one(data):
            logging.info(f"Sensor data {data['uid']} successfully sent to 'Records' collection")
            
    def fetch_records(self, start_ts, end_ts):
        if not self.connected:
            return []
        import time
        start_ts = time.mktime(start_ts.timetuple())
        end_ts = time.mktime(end_ts.timetuple())
        query = {"ts": {"$gte": start_ts, "$lte": end_ts}}
        docs = list(self.coll.find(query))
        logging.info(f"Fetched {len(docs)} records between {start_ts} and {end_ts}")
        return docs
    
    
    
# import datetime
# test = RemoteDB()
# test.connect()
# if test.connected:
#     print("Connected to MongoDB")
#     records = test.fetch_records(datetime.date(2025, 6, 1), datetime.date(2025, 6, 30))
#     print(f"Fetched {len(records)} records")
#     print(pd.DataFrame(records).head().T)