import yfinance as yf
import pandas as pd
import numpy as np
from pymongo import MongoClient, UpdateOne
from datetime import datetime, timedelta
import logging
import time
from typing import List
import sys
import akshare as ak

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

MONGODB_URL = "mongodb://localhost:27017/"
DB_NAME = "sse_stock_db"
COLLECTION_NAME = "stock_daily"

class SSEStockUpdater:
    def __init__(self):
        self.client = MongoClient(MONGODB_URL)
        self.db = self.client[DB_NAME]
        self.collection = self.db[COLLECTION_NAME]
        
    def get_sse_stocks(self) -> List[str]:
        try:
            df = ak.stock_info_a_code_name()
            sse_df = df[df['code'].str.startswith(('6', '688'))]
            stocks = sse_df['code'].tolist()
            logger.info(f"获取到 {len(stocks)} 只上海交易所股票")
            return stocks
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []
    
    def get_latest_date_for_stock(self, ticker: str) -> str:
        latest = self.collection.find_one(
            {"ticker": ticker},
            sort=[("date", -1)]
        )
        if latest:
            return latest['date'].strftime("%Y-%m-%d")
        return "2010-01-01"
    
    def fetch_stock_history(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        try:
            symbol = f"{ticker}.SS"
            df = yf.download(
                symbol,
                start=start_date,
                end=end_date,
                progress=False,
                auto_adjust=True,
                threads=False
            )
            if df.empty:
                return pd.DataFrame()

            df = df.reset_index()
            df = df.rename(columns={
                'Date': 'date',
                'Open': 'open',
                'High': 'high',
                'Low': 'low',
                'Close': 'close',
                'Volume': 'volume'
            })
            df['date'] = pd.to_datetime(df['date']).dt.tz_localize(None)
            df['code'] = f"sh.{ticker}"
            return df[['date', 'code', 'open', 'high', 'low', 'close', 'volume']]
        except Exception as e:
            logger.error(f"获取股票 {ticker} 数据失败: {e}")
            return pd.DataFrame()
    
    def update_stock(self, ticker: str) -> int:
        latest_date = self.get_latest_date_for_stock(ticker)
        today = datetime.now().strftime("%Y-%m-%d")
        
        if latest_date >= today:
            return 0
        
        start = (datetime.strptime(latest_date, "%Y-%m-%d") + timedelta(days=1)).strftime("%Y-%m-%d")
        logger.info(f"更新股票 {ticker}: {start} 至 {today}")
        df = self.fetch_stock_history(ticker, start, today)
        
        if df.empty:
            logger.warning(f"股票 {ticker} 在 {start} 至 {today} 无数据")
            return 0

        if 'date' not in df.columns:
            logger.error(f"DataFrame 中缺少 'date' 列，实际列: {df.columns.tolist()}")
            return 0

        operations = []
        for i in range(len(df)):
            date_val = df['date'].iloc[i]
            date_obj = date_val.to_pydatetime()
            
            code_val = df['code'].iloc[i]
            if not isinstance(code_val, str):
                code_str = str(code_val)
            else:
                code_str = code_val
            ticker_code = code_str.replace('sh.', '')
            
            try:
                open_val = float(df['open'].iloc[i].iloc[0])
                high_val = float(df['high'].iloc[i].iloc[0])
                low_val = float(df['low'].iloc[i].iloc[0])
                close_val = float(df['close'].iloc[i].iloc[0])
                volume_val = float(df['volume'].iloc[i].iloc[0])
            except (TypeError, ValueError) as e:
                logger.error(f"转换数值失败（行 {i}）: {e}")
                continue
            
            doc = {
                "ticker": ticker_code,
                "date": date_obj,
                "open": open_val,
                "high": high_val,
                "low": low_val,
                "close": close_val,
                "volume": volume_val
            }
            operations.append(
                UpdateOne(
                    {"ticker": ticker_code, "date": date_obj},
                    {"$set": doc},
                    upsert=True
                )
            )
        
        if operations:
            result = self.collection.bulk_write(operations)
            logger.info(f"股票 {ticker} 更新完成: {result.upserted_count} 条插入, {result.modified_count} 条更新")
            return result.upserted_count + result.modified_count
        return 0
    
    def update_all_stocks(self, limit: int = None):
        stocks = self.get_sse_stocks()
        if not stocks:
            logger.error("未获取到股票列表")
            return
        
        if limit:
            stocks = stocks[:limit]
        
        logger.info(f"开始更新 {len(stocks)} 只股票")
        
        total_updated = 0
        failed_stocks = []
        
        for i, ticker in enumerate(stocks, 1):
            try:
                time.sleep(0.5)
                count = self.update_stock(ticker)
                total_updated += count
                if i % 50 == 0:
                    logger.info(f"进度: {i}/{len(stocks)}")
            except Exception as e:
                logger.error(f"更新股票 {ticker} 失败: {e}")
                failed_stocks.append(ticker)
        
        logger.info(f"更新完成: 共更新 {total_updated} 条记录")
        if failed_stocks:
            logger.warning(f"失败的股票: {failed_stocks}")

    def update_today_only(self):
        """批量更新今日数据（使用批量下载，抑制错误）"""
        today = datetime.now().strftime("%Y-%m-%d")
        stocks = self.get_sse_stocks()
        if not stocks:
            return

        logger.info(f"开始批量更新今日数据 ({today})，共 {len(stocks)} 只股票")

        batch_size = 50
        updated_count = 0

        for i in range(0, len(stocks), batch_size):
            batch = stocks[i:i+batch_size]
            ticker_symbols = [f"{ticker}.SS" for ticker in batch]

            try:
                df = self._silent_download(ticker_symbols, start=today, end=today)
                if df.empty:
                    logger.debug(f"批次 {i//batch_size+1}: 无数据")
                    continue

                for ticker in batch:
                    symbol = f"{ticker}.SS"
                    if symbol not in df.columns.levels[0]:
                        continue

                    data = df[symbol]
                    if data.empty:
                        continue

                    row = data.iloc[0]
                    if row['Volume'] == 0 or pd.isna(row['Close']):
                        continue

                    date_obj = datetime.strptime(today, "%Y-%m-%d")
                    doc = {
                        "ticker": ticker,
                        "date": date_obj,
                        "open": float(row['Open']),
                        "high": float(row['High']),
                        "low": float(row['Low']),
                        "close": float(row['Close']),
                        "volume": float(row['Volume'])
                    }
                    self.collection.update_one(
                        {"ticker": ticker, "date": doc["date"]},
                        {"$set": doc},
                        upsert=True
                    )
                    updated_count += 1

                logger.info(f"批次 {i//batch_size+1} 完成，已处理 {min(i+batch_size, len(stocks))}/{len(stocks)} 只")

            except Exception as e:
                logger.error(f"批量下载失败: {e}")

            time.sleep(1)

        logger.info(f"今日数据更新完成，共更新 {updated_count} 只股票")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SSE 股票数据更新脚本 (yfinance)")
    parser.add_argument("--mode", choices=["full", "today", "single"], default="today",
                        help="更新模式: full=全量更新, today=仅今日, single=单只")
    parser.add_argument("--ticker", help="单只更新时的股票代码")
    parser.add_argument("--limit", type=int, help="全量更新时的股票数量限制")
    
    args = parser.parse_args()
    
    updater = SSEStockUpdater()
    
    if args.mode == "full":
        updater.update_all_stocks(limit=args.limit)
    elif args.mode == "single":
        if not args.ticker:
            logger.error("请使用 --ticker 指定股票代码")
            sys.exit(1)
        updater.update_stock(args.ticker)
    else:
        updater.update_today_only()