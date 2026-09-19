import os
from pathlib import Path

from dotenv import load_dotenv

load_dotenv()
DATA = Path(os.getenv("ORACLE_DATA_DIR", "data"))
DB_PATH = DATA / "oracle.sqlite3"
ASSETS = ("BTC", "ETH", "SOL")
CONTEXT = 512
HORIZONS = (24, 72)
MODEL_ID = "google/timesfm-2.5-200m-pytorch"
MODEL_REVISION = "1d952420fba87f3c6dee4f240de0f1a0fbc790e3"
EXPERIMENT = "v1-log512-h24-72-hourly"
FEEDS = {
    "CoinDesk": "https://www.coindesk.com/arc/outboundfeeds/rss/",
    "Ethereum Blog": "https://blog.ethereum.org/feed.xml",
}
