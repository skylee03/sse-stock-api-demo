from fastapi import APIRouter, Query, HTTPException
from datetime import datetime
from app.database import stock_collection

router = APIRouter(prefix="/api/v1/stocks", tags=["stocks"])

@router.get("/daily")
async def get_stock_daily(
    ticker: str = Query(..., description="股票代码，如 600000"),
    start_date: str = Query(..., description="开始日期，格式 YYYY-MM-DD"),
    end_date: str = Query(..., description="结束日期，格式 YYYY-MM-DD"),
    fields: str = Query(..., description="返回字段，逗号分隔，如 high,low,volume")
):
    try:
        start = datetime.strptime(start_date, "%Y-%m-%d")
        end = datetime.strptime(end_date, "%Y-%m-%d")
    except ValueError:
        raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")

    if start > end:
        raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")

    requested_fields = [f.strip() for f in fields.split(",") if f.strip()]
    valid_fields = {"open", "high", "low", "close", "volume", "amount"}
    
    projection_fields = {"ticker": 1, "date": 1, "_id": 0}
    for f in requested_fields:
        if f in valid_fields:
            projection_fields[f] = 1

    pipeline = [
        {
            "$match": {
                "ticker": ticker,
                "date": {"$gte": start, "$lte": end}
            }
        },
        {
            "$sort": {"date": 1}
        },
        {
            "$project": projection_fields
        }
    ]

    results = list(stock_collection.aggregate(pipeline))

    if not results:
        raise HTTPException(
            status_code=404,
            detail=f"未找到股票 {ticker} 在 {start_date} 至 {end_date} 的数据"
        )

    for doc in results:
        doc["date"] = doc["date"].date().isoformat()

    return {
        "ticker": ticker,
        "start_date": start_date,
        "end_date": end_date,
        "fields": requested_fields,
        "total": len(results),
        "data": results
    }

@router.get("/tickers")
async def get_all_tickers():
    tickers = stock_collection.distinct("ticker")
    return {"total": len(tickers), "tickers": sorted(tickers)}
