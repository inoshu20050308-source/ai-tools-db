import asyncio
import random
import logging
import sqlite3
import re
from datetime import datetime
from typing import List, Dict, Any, Optional
from dataclasses import dataclass
import pandas as pd
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

# ==========================================
# 0. Configuration & Logging Setup
# ==========================================
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline_error.log", mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class ScraperConfig:
    base_url: str
    target_urls: List[str]
    selectors: Dict[str, str]
    db_path: str = "seo_content.db"
    max_retries: int = 3

# ==========================================
# ここを修正: FutureToolsの「詳細ページ」を直接狙う設定
# ==========================================
CONFIG = ScraperConfig(
    base_url="https://www.futuretools.io",
    # 練習用に、具体的なツールの詳細ページURLをリストに入れています
    target_urls=[
        "https://www.futuretools.io/tools/chatgpt",
        "https://www.futuretools.io/tools/midjourney",
        "https://www.futuretools.io/tools/notion-ai",
    ],
    selectors={
        # 詳細ページ内の要素を指定
        "title": "h1",                         # ツール名
        "description": ".rich-text-block",     # 説明文
        "price": ".pricing-category",          # 価格タグ (Free/Paidなど)
        "image": ".main-image",                # 画像 (クラス名は仮定、なければ失敗ログが出るだけ)
        "specs_table": ".tags-container",      # タグ一覧をスペックとして取得
        
        # 今回は詳細ページ直指定なので以下はダミー（エラー回避用）
        "product_container": "body",
        "link": "a",
        "next_pagination": ".next"
    }
)

USER_AGENTS = [
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36",
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.114 Safari/537.36",
]

# ==========================================
# 1. Scraper Class (Playwright / Async)
# ==========================================
class Scraper:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.data_buffer: List[Dict[str, Any]] = []

    async def _get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    async def _human_like_delay(self):
        await asyncio.sleep(random.uniform(1.0, 3.0))

    async def extract_page_details(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_like_delay()

            s = self.config.selectors

            # タイトル取得（必須）
            if await page.locator(s["title"]).count() > 0:
                title = await page.locator(s["title"]).first.inner_text()
            else:
                logger.warning(f"Title not found for {url}")
                return None

            # 説明文取得
            description = ""
            if await page.locator(s["description"]).count() > 0:
                description = await page.locator(s["description"]).first.inner_text()

            # 価格/タグ取得
            price_text = ""
            if await page.locator(s["price"]).count() > 0:
                price_text = await page.locator(s["price"]).first.inner_text()
            
            # スペック（タグ情報）取得
            specs = ""
            if await page.locator(s["specs_table"]).count() > 0:
                specs = await page.locator(s["specs_table"]).first.inner_text()

            # 画像URL
            image_url = ""
            # imgタグの取得ロジックはサイト依存が強いため、今回はエラー回避のためスキップするか簡易実装
            # img_element = page.locator(s["image"]).first ... (省略)

            logger.info(f"Scraped: {title}")

            return {
                "url": url,
                "title": title,
                "description": description,
                "raw_price": price_text,
                "image_url": image_url,
                "specs": specs, 
                "scraped_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"Failed to scrape {url}: {e}")
            return None

    async def run(self) -> List[Dict[str, Any]]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=await self._get_random_ua())
            page = await context.new_page()

            for target_url in self.config.target_urls:
                try:
                    data = await self.extract_page_details(page, target_url)
                    if data:
                        self.data_buffer.append(data)
                except Exception as e:
                    logger.error(f"Critical error processing {target_url}: {e}")
                    continue

            await browser.close()
            return self.data_buffer

# ==========================================
# 2. Cleaner Class (Pandas)
# ==========================================
class Cleaner:
    def __init__(self):
        pass

    def normalize_text(self, text: str) -> str:
        if pd.isna(text):
            return ""
        return " ".join(str(text).split())

    def process(self, raw_data: List[Dict[str, Any]]) -> pd.DataFrame:
        if not raw_data:
            logger.warning("No data to clean.")
            return pd.DataFrame()

        df = pd.DataFrame(raw_data)
        
        # 欠損値処理
        if 'title' in df.columns:
            df.dropna(subset=['title'], inplace=True)

        # 重複排除
        df.drop_duplicates(subset=['url'], keep='last', inplace=True)

        # テキスト正規化
        text_columns = ['title', 'description', 'specs', 'raw_price']
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].apply(self.normalize_text)

        # priceカラムの整理（raw_priceをそのままpriceへ）
        if 'raw_price' in df.columns:
            df['price'] = df['raw_price'] 

        return df

# ==========================================
# 3. Storage Class (SQLite)
# ==========================================
class Storage:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._init_db()

    def _init_db(self):
        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()
        
        # priceカラムの定義をINTEGERからTEXTへ変更（Free/Paidなどの文字列が入るため）
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            price TEXT,
            image_url TEXT,
            specs TEXT,
            scraped_at TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        cursor.execute(create_table_sql)
        conn.commit()
        conn.close()

    def save(self, df: pd.DataFrame):
        if df.empty:
            logger.info("No data to save.")
            return

        conn = sqlite3.connect(self.db_path)
        cursor = conn.cursor()

        try:
            records = df.to_dict(orient='records')
            
            upsert_sql = """
            INSERT INTO products (url, title, description, price, image_url, specs, scraped_at)
            VALUES (:url, :title, :description, :price, :image_url, :specs, :scraped_at)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                price=excluded.price,
                image_url=excluded.image_url,
                specs=excluded.specs,
                scraped_at=excluded.scraped_at,
                updated_at=CURRENT_TIMESTAMP;
            """
            
            cursor.executemany(upsert_sql, records)
            conn.commit()
            logger.info(f"Successfully upserted {len(records)} records into SQLite.")
            
        except Exception as e:
            logger.error(f"Database error: {e}")
            conn.rollback()
        finally:
            conn.close()

# ==========================================
# 4. Main Pipeline Execution
# ==========================================
async def main():
    logger.info("Starting Programmatic SEO Data Pipeline (FutureTools Target)...")

    # 1. Scraper
    scraper = Scraper(CONFIG)
    raw_data = await scraper.run()

    if not raw_data:
        logger.error("Scraping finished with no data.")
        return

    # 2. Cleaner
    cleaner = Cleaner()
    cleaned_df = cleaner.process(raw_data)

    # 3. Storage
    storage = Storage(CONFIG.db_path)
    storage.save(cleaned_df)

    logger.info("Pipeline completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())