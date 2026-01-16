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

# FutureTools用の設定（既存維持）
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

# ---------------------------------------------------------
# Security Evasion: Modern User-Agents List
# ---------------------------------------------------------
USER_AGENTS = [
    # Windows 10 / Chrome 120
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
    # Windows 10 / Edge
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36 Edg/120.0.0.0",
    # Mac / Chrome
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
]

# ==========================================
# 1. Scraper Class (Playwright / Async)
# ==========================================
class Scraper:
    def __init__(self, config: ScraperConfig):
        self.config = config
        self.data_buffer: List[Dict[str, Any]] = []

    def _get_random_ua(self) -> str:
        return random.choice(USER_AGENTS)

    async def _human_like_delay(self):
        """1秒〜3秒のランダム待機で人間らしさを演出"""
        await asyncio.sleep(random.uniform(1.0, 3.0))

    # ---------------------------------------------------------
    # 既存機能 1: FutureTools
    # ---------------------------------------------------------
    async def extract_future_tools(self, page: Page, url: str) -> Optional[Dict[str, Any]]:
        try:
            await page.goto(url, wait_until="domcontentloaded", timeout=30000)
            await self._human_like_delay()

            s = self.config.selectors

            if await page.locator(s["title"]).count() > 0:
                title = await page.locator(s["title"]).first.inner_text()
            else:
                logger.warning(f"[FutureTools] Title not found for {url}")
                return None

            description = ""
            if await page.locator(s["description"]).count() > 0:
                description = await page.locator(s["description"]).first.inner_text()

            price_text = ""
            if await page.locator(s["price"]).count() > 0:
                price_text = await page.locator(s["price"]).first.inner_text()
            
            specs = ""
            if await page.locator(s["specs_table"]).count() > 0:
                specs = await page.locator(s["specs_table"]).first.inner_text()

            logger.info(f"[FutureTools] Scraped: {title}")

            return {
                "url": url,
                "title": title,
                "description": description,
                "raw_price": price_text,
                "image_url": "",
                "specs": specs,
                "category": "AI Tool",
                "scraped_at": datetime.now().isoformat()
            }

        except Exception as e:
            logger.error(f"[FutureTools] Failed to scrape {url}: {e}")
            return None

    # ---------------------------------------------------------
    # 既存機能 2: Zenn
    # ---------------------------------------------------------
    async def scrape_zenn_trends(self, page: Page) -> List[Dict[str, Any]]:
        zenn_url = "https://zenn.dev"
        zenn_data = []
        
        try:
            logger.info("[Zenn] Starting trend scraping...")
            await page.goto(zenn_url, wait_until="domcontentloaded", timeout=30000)
            await self._human_like_delay()

            articles = page.locator("article")
            count = await articles.count()
            logger.info(f"[Zenn] Found {count} articles.")

            for i in range(min(count, 10)):
                try:
                    article_row = articles.nth(i)
                    
                    title_el = article_row.locator("h2")
                    if await title_el.count() == 0:
                        continue
                    title = await title_el.first.inner_text()

                    link_el = article_row.locator("a[href^='/']").first
                    if await link_el.count() == 0:
                        continue
                    
                    href = await link_el.get_attribute("href")
                    full_url = f"https://zenn.dev{href}"

                    description = f"Zennのトレンド記事: {title}"

                    zenn_data.append({
                        "url": full_url,
                        "title": title,
                        "description": description,
                        "raw_price": "Free",
                        "image_url": "",
                        "specs": "Tech Trend",
                        "category": "Tech News",
                        "scraped_at": datetime.now().isoformat()
                    })
                    logger.info(f"[Zenn] Picked: {title[:20]}...")

                except Exception as e:
                    logger.warning(f"[Zenn] Error scraping article index {i}: {e}")
                    continue

        except Exception as e:
            logger.error(f"[Zenn] Top page scraping failed: {e}")

        return zenn_data

    # ---------------------------------------------------------
    # 新機能 3: 価格.com ノートPCランキング (セレクタ強化版)
    # ---------------------------------------------------------
    async def scrape_kakaku_ranking(self, page: Page) -> List[Dict[str, Any]]:
        """
        価格.comのノートPCランキングからデータを取得する。
        URL: https://kakaku.com/pc/note-pc/ranking_0020/
        
        【修正点】
        - 複数のセレクタを順次試して、リンクと価格を確実に取得する
        - エラーがあってもスキップして続行する
        """
        kakaku_url = "https://kakaku.com/pc/note-pc/ranking_0020/"
        gadget_data = []

        try:
            logger.info("[Kakaku] Visiting Note PC Ranking...")
            
            # ページ遷移
            await page.goto(kakaku_url, wait_until="domcontentloaded", timeout=60000)
            
            # 商品ボックス (.rkgBox) が表示されるまで待機
            try:
                await page.wait_for_selector(".rkgBox", timeout=20000)
            except PlaywrightTimeoutError:
                title = await page.title()
                logger.error(f"[Kakaku] Wait timeout. Page structure might be different. Title: {title}")
                return []

            await self._human_like_delay()

            # 商品ボックスを全て取得
            boxes = page.locator(".rkgBox")
            count = await boxes.count()
            limit = min(count, 5) # 上位5件
            
            logger.info(f"[Kakaku] Found {count} items. Fetching top {limit}...")

            for i in range(limit):
                try:
                    # i番目のボックスを取得
                    box = boxes.nth(i)

                    # -------------------------------------------------
                    # 1. 商品名とリンクの取得 (Multi-Selector Trial)
                    # -------------------------------------------------
                    link_el = None
                    
                    # 候補リスト: 上から順に試す
                    selectors_to_try = [
                        "a.ckitemLink",         # パターン1: 一般的な商品リンク
                        ".rankingItemName a",   # パターン2: ランキング用クラス
                        ".ranking-read a",      # パターン3: 別レイアウト
                        "td.textL a",           # パターン4: テーブル構造
                        "a[href*='/item/']"     # パターン5: 最終手段 (URLの一部)
                    ]

                    for sel in selectors_to_try:
                        candidate = box.locator(sel).first
                        if await candidate.count() > 0:
                            link_el = candidate
                            # logger.info(f"[Kakaku] Rank {i+1}: Found link via '{sel}'")
                            break
                    
                    if not link_el:
                        logger.warning(f"[Kakaku] Rank {i+1}: Link element not found (Skipping).")
                        continue
                        
                    raw_title = await link_el.inner_text()
                    href = await link_el.get_attribute("href")
                    
                    # テキストクリーニング
                    title = raw_title.replace('\n', ' ').strip()
                    title = re.sub(r'\s+', ' ', title)

                    # -------------------------------------------------
                    # 2. 価格の取得 (Multi-Selector Trial)
                    # -------------------------------------------------
                    price_el = None
                    price_selectors = [
                        ".rkgPrice .yen",
                        ".price .yen",
                        "span.yen",
                        ".price"
                    ]
                    
                    raw_price = "Unknown"
                    for sel in price_selectors:
                        candidate = box.locator(sel).first
                        if await candidate.count() > 0:
                            price_text = await candidate.inner_text()
                            # ¥マークやカンマを除去
                            raw_price = price_text.replace("¥", "").replace(",", "").strip()
                            break

                    description = f"価格.com ノートPCランキング上位: {title}"

                    gadget_data.append({
                        "url": href,
                        "title": title,
                        "description": description,
                        "raw_price": raw_price,
                        "image_url": "",
                        "specs": f"Kakaku.com Ranking #{i+1}",
                        "category": "Gadget",
                        "scraped_at": datetime.now().isoformat()
                    })
                    
                    logger.info(f"[Kakaku] Picked Rank {i+1}: {title[:30]}...")

                except Exception as e:
                    logger.warning(f"[Kakaku] Error scraping rank {i+1}: {e}")
                    continue

        except Exception as e:
            logger.error(f"[Kakaku] Scraping failed: {e}")

        return gadget_data

    # ---------------------------------------------------------
    # パイプライン実行メインフロー
    # ---------------------------------------------------------
    async def run(self) -> List[Dict[str, Any]]:
        async with async_playwright() as p:
            # -----------------------------------------------------
            # Advanced Stealth Configuration
            # -----------------------------------------------------
            browser = await p.chromium.launch(
                headless=True,
                args=[
                    '--disable-blink-features=AutomationControlled',
                    '--no-sandbox',
                    '--disable-infobars',
                    '--disable-dev-shm-usage',
                    '--disable-extensions',
                    '--disable-gpu'
                ]
            )
            
            context = await browser.new_context(
                user_agent=self._get_random_ua(),
                locale='ja-JP',
                timezone_id='Asia/Tokyo',
                viewport={'width': 1280, 'height': 720},
                java_script_enabled=True,
                extra_http_headers={
                    'referer': 'https://www.google.com/'
                },
                permissions=['geolocation']
            )
            
            await context.add_init_script("""
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => undefined
                });
            """)

            page = await context.new_page()

            # 1. FutureTools
            for target_url in self.config.target_urls:
                try:
                    data = await self.extract_future_tools(page, target_url)
                    if data:
                        self.data_buffer.append(data)
                except Exception as e:
                    logger.error(f"Critical error processing {target_url}: {e}")

            # 2. Zenn
            zenn_articles = await self.scrape_zenn_trends(page)
            self.data_buffer.extend(zenn_articles)

            # 3. Kakaku.com Gadgets
            kakaku_gadgets = await self.scrape_kakaku_ranking(page)
            self.data_buffer.extend(kakaku_gadgets)

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
        
        if 'title' in df.columns:
            df.dropna(subset=['title'], inplace=True)

        df.drop_duplicates(subset=['url'], keep='last', inplace=True)

        text_columns = ['title', 'description', 'specs', 'raw_price']
        for col in text_columns:
            if col in df.columns:
                df[col] = df[col].apply(self.normalize_text)

        if 'raw_price' in df.columns:
            df['price'] = df['raw_price'] 
            
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
        
        cursor.execute("PRAGMA table_info(products)")
        columns = [info[1] for info in cursor.fetchall()]
        
        if "category" not in columns:
            logger.info("Migrating Database: Adding 'category' column...")
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
    logger.info("Starting SEO Data Pipeline (FutureTools, Zenn, Kakaku.com)...")

    scraper = Scraper(CONFIG)
    raw_data = await scraper.run()

    if not raw_data:
        logger.error("Scraping finished with no data.")
        return

    cleaner = Cleaner()
    cleaned_df = cleaner.process(raw_data)

    storage = Storage(CONFIG.db_path)
    storage.save(cleaned_df)

    logger.info("Pipeline completed successfully.")

if __name__ == "__main__":
    asyncio.run(main())