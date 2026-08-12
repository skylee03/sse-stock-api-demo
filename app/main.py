from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.routes import stocks

app = FastAPI(
    title="SSE Stock Data API",
    description="上海证券交易所股票历史数据 API",
    version="1.0.0"
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(stocks.router)

@app.get("/")
async def root():
    return {
        "message": "SSE Stock Data API",
        "endpoints": [
            "GET /api/v1/stocks/daily?ticker=600000&start_date=2024-01-01&end_date=2024-12-31&fields=high,low,volume",
            "GET /api/v1/stocks/tickers"
        ]
    }
