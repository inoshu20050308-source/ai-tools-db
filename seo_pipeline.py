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

# FutureTools用の設定（既存）
CONFIG = ScraperConfig(
    base_url="https://www.futuretools.io",
    target_urls=[
        "https://www.futuretools.io/tools/chatgpt",
        "https://www.futuretools.io/tools/midjourney",
        "https://www.futuretools.io/tools/notion-ai",
    ],
    selectors={
        "title": "h1",
        "description": ".rich-text-block",
        "price": ".pricing-category",
        "image": ".main-image",
        "specs_table": ".tags-container",
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

    # ---------------------------------------------------------
    # 既存機能: FutureToolsの詳細ページスクレイピング
    # ---------------------------------------------------------
    async def extract_future_tools(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        """FutureToolsの個別ページからデータを取得"""
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_like_delay()

            s = self.config.selectors

            # タイトル取得
            if await page.locator(s["title"]).count() > 0:
                title = await page.locator(s["title"]).first.inner_text()
            else:
                logger.warning(f"[FutureTools] Title not found for {url}")
                return None

            # 説明文取得
            description = ""
            if await page.locator(s["description"]).count() > 0:
                description = await page.locator(s["description"]).first.inner_text()

            # 価格取得
            price_text = ""
            if await page.locator(s["price"]).count() > 0:
                price_text = await page.locator(s["price"]).first.inner_text()
            
            # スペック（タグ）取得
            specs = ""
            if await page.locator(s["specs_table"]).count() > 0:
                specs = await page.locator(s["specs_table"]).first.inner_text()

            logger.info(f"[FutureTools] Scraped: {title}")

            return {
                "url": url,
                "title": title,
                "description": description,
                "raw_price": price_text,
                "image_url": "", # 簡易実装のため空
                "specs": specs,
                "category": "AI Tool", # カテゴリを明示
                "scraped_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"[FutureTools] Failed to scrape {url}: {e}")
            return None

    # ---------------------------------------------------------
    # 新機能: Zennのトレンドスクレイピング
    # ---------------------------------------------------------
    async def scrape_zenn_trends(self, page: Page) -> List[Dict[str, Any]]:
        """
        Zennのトップページからトレンド記事を取得する。
        動的なクラス名(ArticleList_title__xxx)には依存せず、
        セマンティックなタグ(article, h2)を使用する。
        """
        zenn_url = "https://zenn.dev"
        zenn_data = []
        
        try:
            logger.info("[Zenn] Starting trend scraping...")
            await page.goto(zenn_url, wait_until="domcontentloaded", timeout=30000)
            await self._human_like_delay()

            # 記事コンテナ（articleタグ）を取得
            # Zennはトレンド一覧などで <article> タグを使用している
            articles = page.locator("article")
            count = await articles.count()
            logger.info(f"[Zenn] Found {count} articles.")

            for i in range(min(count, 20)): # 上位20件のみ取得
                try:
                    article_row = articles.nth(i)
                    
                    # タイトル取得 (article内の h2)
                    title_el = article_row.locator("h2")
                    if await title_el.count() == 0:
                        continue
                    title = await title_el.first.inner_text()

                    # リンク取得 (article内の aタグのhref)
                    # 記事リンクは通常、タイトルを囲むか、article直下のaタグ
                    link_el = article_row.locator("a[href^='/']").first
                    if await link_el.count() == 0:
                        continue
                    
                    href = await link_el.get_attribute("href")
                    full_url = f"https://zenn.dev{href}"

                    # 概要 (詳細ページには行かず、テンプレートで生成)
                    description = f"Zennのトレンド記事: {title}"

                    zenn_data.append({
                        "url": full_url,
                        "title": title,
                        "description": description,
                        "raw_price": "Free",     # Zennは基本無料
                        "image_url": "",
                        "specs": "Tech Trend",   # スペック欄にタグ代わり
                        "category": "Tech News", # カテゴリ: 技術ニュース
                        "scraped_at": datetime.now().isoformat()
                    })
                    
                    logger.info(f"[Zenn] Picked: {title}")

                except Exception as e:
                    logger.warning(f"[Zenn] Error scraping article index {i}: {e}")
                    continue

        except Exception as e:
            logger.error(f"[Zenn] Top page scraping failed: {e}")

        return zenn_data

    async def run(self) -> List[Dict[str, Any]]:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            context = await browser.new_context(user_agent=await self._get_random_ua())
            page = await context.new_page()

            # 1. FutureTools (既存リスト) の処理
            for target_url in self.config.target_urls:
                try:
                    data = await self.extract_future_tools(page, target_url)
                    if data:
                        self.data_buffer.append(data)
                except Exception as e:
                    logger.error(f"Critical error processing {target_url}: {e}")

            # 2. Zenn (トレンド) の処理を追加
            zenn_articles = await self.scrape_zenn_trends(page)
            self.data_buffer.extend(zenn_articles)

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

        # 重複排除 (URLベース)
        df.drop_duplicates(subset=['url'], keep='last', inplace=True)

        # テキスト正規化
        text_columns = ['title', 'description', 'specs', 'raw_price']
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].apply(self.normalize_text)

        # priceカラム
        if 'raw_price' in df.columns:
            df['price'] = df['raw_price'] 
            
        # categoryカラムが欠落している場合の安全策（基本はScraperで入る）
        if 'category' not in df.columns:
             df['category'] = 'Uncategorized'

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
        
        # テーブル作成（categoryカラムを追加）
        # priceはINTEGERではなくTEXTに変更（'Free'等の文字列が入るため）
        create_table_sql = """
        CREATE TABLE IF NOT EXISTS products (
            url TEXT PRIMARY KEY,
            title TEXT,
            description TEXT,
            price TEXT,
            image_url TEXT,
            specs TEXT,
            category TEXT,
            scraped_at TEXT,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        );
        """
        cursor.execute(create_table_sql)
        
        # ---------------------------------------------------------
        # DB Migration: categoryカラムが存在しない場合の追加処理
        # ---------------------------------------------------------
        cursor.execute("PRAGMA table_info(products)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "category" not in columns:
            logger.info("Migrating Database: Adding 'category' column...")
            # 既存のレコードは 'AI Tool' とみなす
            cursor.execute("ALTER TABLE products ADD COLUMN category TEXT DEFAULT 'AI Tool'")
            conn.commit()
        else:
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
            
            # Upsert SQLに category を追加
            upsert_sql = """
            INSERT INTO products (url, title, description, price, image_url, specs, category, scraped_at)
            VALUES (:url, :title, :description, :price, :image_url, :specs, :category, :scraped_at)
            ON CONFLICT(url) DO UPDATE SET
                title=excluded.title,
                description=excluded.description,
                price=excluded.price,
                image_url=excluded.image_url,
                specs=excluded.specs,
                category=excluded.category,
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
    logger.info("Starting SEO Data Pipeline (Targets: FutureTools & Zenn)...")

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