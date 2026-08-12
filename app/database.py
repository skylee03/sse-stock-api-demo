from pymongo import MongoClient
from app.config import MONGODB_URL, DB_NAME

client = MongoClient(MONGODB_URL)
db = client[DB_NAME]
stock_collection = db["stock_daily"]
