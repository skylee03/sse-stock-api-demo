from pydantic import BaseModel
from typing import List, Optional
from datetime import date

class StockDataResponse(BaseModel):
    ticker: str
    date: date
    open: Optional[float] = None
    high: Optional[float] = None
    low: Optional[float] = None
    close: Optional[float] = None
    volume: Optional[float] = None
    amount: Optional[float] = None

class StockQueryResponse(BaseModel):
    ticker: str
    start_date: date
    end_date: date
    fields: List[str]
    data: List[StockDataResponse]
