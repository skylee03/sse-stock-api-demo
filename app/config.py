import os

MONGODB_URL = os.getenv("MONGODB_URL", "mongodb://localhost:27017")
DB_NAME = os.getenv("DB_NAME", "sse_stock_db")
COLLECTION_NAME = "stock_daily"
