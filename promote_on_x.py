import asyncio
import sqlite3
import os
import logging
import hashlib
from typing import Optional, Dict, Any
from dotenv import load_dotenv
from playwright.async_api import async_playwright, Page, TimeoutError as PlaywrightTimeoutError

# ==========================================
# 0. Configuration & Setup
# ==========================================

# 環境変数の読み込み
load_dotenv()

# 設定値
DB_PATH = "seo_content.db"
X_USERNAME = os.getenv("X_USERNAME")
X_PASSWORD = os.getenv("X_PASSWORD")
X_EMAIL = os.getenv("X_EMAIL")
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://example.com")
COOKIE_FILE = "x_cookies.json"  # Cookie保存用ファイル

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("promotion.log", mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

# ==========================================
# 1. Database Class
# ==========================================
class DatabaseHandler:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._migrate_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _migrate_db(self):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(products)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if "promoted" not in columns:
                logger.info("Column 'promoted' not found. Adding column...")
                cursor.execute("ALTER TABLE products ADD COLUMN promoted INTEGER DEFAULT 0")
                conn.commit()
            else:
                logger.debug("Column 'promoted' already exists.")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
        finally:
            conn.close()

    def fetch_candidate_article(self) -> Optional[Dict[str, Any]]:
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            query = """
            SELECT url, title, category 
            FROM products 
            WHERE generated_body IS NOT NULL AND generated_body != '' AND promoted = 0
            ORDER BY scraped_at ASC
            LIMIT 1
            """
            cursor.execute(query)
            row = cursor.fetchone()
            return dict(row) if row else None
        except Exception as e:
            logger.error(f"Failed to fetch candidate: {e}")
            return None
        finally:
            conn.close()

    def mark_as_promoted(self, url: str):
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("UPDATE products SET promoted = 1 WHERE url = ?", (url,))
            conn.commit()
            logger.info(f"Marked as promoted: {url}")
        except Exception as e:
            logger.error(f"Failed to update status: {e}")
        finally:
            conn.close()

# ==========================================
# 2. X (Twitter) Promoter Class
# ==========================================
class XPromoter:
    def __init__(self):
        if not X_USERNAME or not X_PASSWORD:
            raise ValueError("X_USERNAME or X_PASSWORD not set in .env")

    def generate_article_url(self, original_url: str) -> str:
        hash_id = hashlib.md5(original_url.encode('utf-8')).hexdigest()
        base = SITE_BASE_URL.rstrip("/")
        return f"{base}/tools/{hash_id}.html"

    async def post_to_x(self, article: Dict[str, Any]):
        """Playwrightを使ってXに投稿する（Cookie対応版）"""
        
        target_url = self.generate_article_url(article['url'])
        title = article['title']
        
        post_text = f"""【新着記事】
{title}

#AI #Tech #ガジェット
{target_url}"""

        logger.info(f"Starting X promotion for: {title}")

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False, slow_mo=50)
            
            # ---------------------------------------------------------
            # 1. コンテキスト作成 (Cookieがあれば読み込む)
            # ---------------------------------------------------------
            context_args = {
                "user_agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "locale": "ja-JP"
            }
            
            if os.path.exists(COOKIE_FILE):
                logger.info(f"Cookie file found ({COOKIE_FILE}). Loading session...")
                context = await browser.new_context(storage_state=COOKIE_FILE, **context_args)
                has_cookie = True
            else:
                logger.info("No cookie file found. Starting fresh session.")
                context = await browser.new_context(**context_args)
                has_cookie = False

            context.set_default_timeout(60000)
            page = await context.new_page()

            try:
                # ---------------------------------------------------------
                # 2. ログイン状態の確認
                # ---------------------------------------------------------
                logged_in = False
                
                if has_cookie:
                    logger.info("Navigating to Home page with cookies...")
                    await page.goto("https://x.com/home", wait_until="domcontentloaded")
                    
                    try:
                        # 投稿ボタンが表示されればログイン成功とみなす
                        await page.wait_for_selector('[data-testid="SideNav_NewTweet_Button"]', timeout=10000)
                        logger.info("Session is valid. Skipped login process.")
                        logged_in = True
                    except Exception:
                        logger.warning("Session expired or invalid. Falling back to manual login.")
                        logged_in = False
                
                # ---------------------------------------------------------
                # 3. 未ログインならログイン処理を実行 (従来フロー)
                # ---------------------------------------------------------
                if not logged_in:
                    logger.info("Starting manual login process...")
                    await self._perform_login(page)
                    
                    # ログイン成功後、Cookieを保存しておく
                    logger.info(f"Login successful. Saving cookies to {COOKIE_FILE}...")
                    await context.storage_state(path=COOKIE_FILE)

                # ---------------------------------------------------------
                # 4. 投稿処理 (共通フロー)
                # ---------------------------------------------------------
                logger.info("Proceeding to tweet composition...")
                
                # ツイート作成ボタンクリック
                await page.click('[data-testid="SideNav_NewTweet_Button"]')
                
                # ダイアログ待機
                textarea_selector = '[data-testid="tweetTextarea_0"]'
                await page.wait_for_selector(textarea_selector, state='visible')
                
                # テキスト入力
                logger.info("Typing tweet content...")
                await page.click(textarea_selector)
                await page.keyboard.type(post_text, delay=50) 
                await asyncio.sleep(2)

                # 投稿ボタン押下
                logger.info("Clicking post button...")
                post_button_selector = '[data-testid="tweetButton"]'
                await page.wait_for_selector(post_button_selector, state='visible')
                await page.click(post_button_selector)
                
                # 送信完了待機
                await asyncio.sleep(5)
                logger.info("Successfully posted to X!")
                
                return True

            except PlaywrightTimeoutError as te:
                logger.error(f"Timeout Error: {te}")
                await page.screenshot(path="debug_error.png")
                return False
            except Exception as e:
                logger.error(f"Unexpected Error: {e}")
                await page.screenshot(path="debug_error.png")
                return False
            finally:
                await browser.close()

    async def _perform_login(self, page: Page):
        """ログイン処理の実装 (未ログイン時のみ呼ばれる)"""
        logger.info("Navigating to login page...")
        await page.goto("https://x.com/i/flow/login", wait_until="domcontentloaded")

        # ユーザー名入力
        logger.info("Entering username...")
        await page.wait_for_selector('input[autocomplete="username"]', state='visible')
        await page.fill('input[autocomplete="username"]', X_USERNAME)
        await page.wait_for_timeout(1000)
        await page.keyboard.press("Enter")

        # パスワード or 本人確認 分岐
        logger.info("Checking for next step (Password or Verification)...")
        await page.wait_for_selector('input[name="password"], input[name="text"]', state='visible')

        if await page.is_visible('input[name="text"]'):
            logger.warning("Verification detected. Entering email...")
            if not X_EMAIL:
                raise ValueError("X_EMAIL is missing for verification.")
            await page.fill('input[name="text"]', X_EMAIL)
            await page.wait_for_timeout(1000)
            
            # 次へボタンのクリック試行
            if await page.is_visible('[data-testid="ocfEnterTextNextButton"]'):
                await page.click('[data-testid="ocfEnterTextNextButton"]')
            else:
                await page.keyboard.press("Enter")
                
            await page.wait_for_selector('input[name="password"]', state='visible')

        # パスワード入力
        logger.info("Entering password...")
        await page.fill('input[name="password"]', X_PASSWORD)
        await page.wait_for_timeout(1000)
        await page.keyboard.press("Enter")
        
        # ログイン完了待機
        logger.info("Waiting for login completion...")
        await page.wait_for_selector('[data-testid="SideNav_NewTweet_Button"]', timeout=30000)

# ==========================================
# 3. Main Execution Flow
# ==========================================
async def main():
    logger.info("Starting X Promotion Pipeline...")

    # DBハンドラの初期化
    db = DatabaseHandler(DB_PATH)
    
    # 投稿候補の取得
    article = db.fetch_candidate_article()
    
    if not article:
        logger.info("No articles available for promotion. Exiting.")
        return

    logger.info(f"Candidate article found: {article['title']}")

    # Xへの投稿処理
    try:
        promoter = XPromoter()
        success = await promoter.post_to_x(article)

        if success:
            db.mark_as_promoted(article['url'])
        else:
            logger.error("Promotion failed. Check debug_error.png.")

    except ValueError as e:
        logger.error(f"Configuration error: {e}")
    except Exception as e:
        logger.error(f"Unexpected error: {e}")

if __name__ == "__main__":
    asyncio.run(main())