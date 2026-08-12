import baostock as bs
import pandas as pd
from pymongo import MongoClient, UpdateOne
from datetime import datetime, timedelta
import logging
import sys
from typing import List

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
        lg = bs.login()
        if lg.error_code != '0':
            logger.error(f"BaoStock 登录失败: {lg.error_msg}")
            return []
        
        try:
            rs = bs.query_all_stock(day=datetime.now().strftime("%Y-%m-%d"))
            df = rs.get_data()
            
            sse_df = df[df['code'].str.startswith('sh.')]
            stocks = [code.replace('sh.', '') for code in sse_df['code'].tolist()]
            
            logger.info(f"获取到 {len(stocks)} 只上海交易所股票")
            return stocks
        except Exception as e:
            logger.error(f"获取股票列表失败: {e}")
            return []
        finally:
            bs.logout()
    
    def get_latest_date_for_stock(self, ticker: str) -> str:
        latest = self.collection.find_one(
            {"ticker": ticker},
            sort=[("date", -1)]
        )
        if latest:
            return latest['date'].strftime("%Y-%m-%d")
        return "2010-01-01"
    
    def fetch_stock_history(self, ticker: str, start_date: str, end_date: str) -> pd.DataFrame:
        lg = bs.login()
        if lg.error_code != '0':
            logger.error(f"BaoStock 登录失败: {lg.error_msg}")
            return pd.DataFrame()
        
        try:
            rs = bs.query_history_k_data_plus(
                f"sh.{ticker}",
                "date,code,open,high,low,close,volume,amount",
                start_date=start_date,
                end_date=end_date,
                frequency="d",
                adjustflag="3"
            )
            
            data_list = []
            while (rs.error_code == '0') and rs.next():
                data_list.append(rs.get_row_data())
            
            if data_list:
                df = pd.DataFrame(data_list, columns=rs.fields)
                return df
            return pd.DataFrame()
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
            return 0
        
        operations = []
        for _, row in df.iterrows():
            doc = {
                "ticker": row['code'].replace('sh.', ''),
                "date": datetime.strptime(row['date'], '%Y-%m-%d'),
                "open": float(row['open']),
                "high": float(row['high']),
                "low": float(row['low']),
                "close": float(row['close']),
                "volume": float(row['volume']),
                "amount": float(row['amount'])
            }
            
            operations.append(
                UpdateOne(
                    {"ticker": doc["ticker"], "date": doc["date"]},
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
        today = datetime.now().strftime("%Y-%m-%d")
        stocks = self.get_sse_stocks()
        
        if not stocks:
            return
        
        logger.info(f"开始更新 {len(stocks)} 只股票的今日数据 ({today})")
        
        for ticker in stocks:
            try:
                existing = self.collection.find_one({
                    "ticker": ticker,
                    "date": datetime.strptime(today, "%Y-%m-%d")
                })
                if existing:
                    continue
                
                df = self.fetch_stock_history(ticker, today, today)
                if not df.empty:
                    doc = {
                        "ticker": ticker,
                        "date": datetime.strptime(today, "%Y-%m-%d"),
                        "open": float(df.iloc[0]['open']),
                        "high": float(df.iloc[0]['high']),
                        "low": float(df.iloc[0]['low']),
                        "close": float(df.iloc[0]['close']),
                        "volume": float(df.iloc[0]['volume']),
                        "amount": float(df.iloc[0]['amount'])
                    }
                    self.collection.update_one(
                        {"ticker": ticker, "date": doc["date"]},
                        {"$set": doc},
                        upsert=True
                    )
            except Exception as e:
                logger.error(f"更新 {ticker} 今日数据失败: {e}")

if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="SSE 股票数据更新脚本")
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