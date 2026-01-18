import os
import sqlite3
import logging
import hashlib
import google.generativeai as genai
from dotenv import load_dotenv

# ==========================================
# 設定 & セットアップ
# ==========================================
load_dotenv()

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
if not GEMINI_API_KEY:
    raise ValueError("GEMINI_API_KEY is not set in .env")

genai.configure(api_key=GEMINI_API_KEY)

# 安定版の最新モデルを指定
model = genai.GenerativeModel("gemini-flash-latest")

DB_PATH = "seo_content.db"
SITE_BASE_URL = os.getenv("SITE_BASE_URL", "https://techino35.github.io/ai-tools-db")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

class ContentGenerator:
    def __init__(self, db_path: str):
        self.db_path = db_path

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _generate_text_with_gemini(self, prompt: str) -> str:
        """Gemini APIを呼び出してテキストを生成"""
        try:
            response = model.generate_content(prompt)
            return response.text
        except Exception as e:
            logger.error(f"Gemini API Error: {e}")
            return ""

    def _save_article(self, url: str, title: str, body: str, category: str):
        """生成された記事をDBに保存"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            # 【修正箇所】id ではなく url をチェックする
            cursor.execute("SELECT url FROM products WHERE url = ?", (url,))
            row = cursor.fetchone()

            if row:
                # 更新
                cursor.execute("""
                    UPDATE products 
                    SET generated_body = ?, title = ?, category = ? 
                    WHERE url = ?
                """, (body, title, category, url))
                logger.info(f"Updated article: {title}")
            else:
                # 新規作成（テーブル定義に合わせてカラムを指定）
                cursor.execute("""
                    INSERT INTO products (url, title, generated_body, category, scraped_at)
                    VALUES (?, ?, ?, ?, CURRENT_TIMESTAMP)
                """, (url, title, body, category))
                logger.info(f"Created new article: {title}")
            
            conn.commit()
        except Exception as e:
            logger.error(f"DB Save Error: {e}")
        finally:
            conn.close()

    def generate_article(self, target_keyword: str = None):
        """記事生成メイン処理"""
        
        # 指名生産モード
        if target_keyword:
            logger.info(f"Target keyword provided: {target_keyword}")
            
            title = f"【入門】{target_keyword}とは？初心者向け徹底解説"
            category = "Tech News"
            
            # 仮想URLの生成
            url_hash = hashlib.md5(target_keyword.encode()).hexdigest()
            dummy_url = f"{SITE_BASE_URL}/keyword/{url_hash}.html"

            prompt = f"""
            あなたはプロのテックライターです。以下のテーマについて、Markdown形式でブログ記事を書いてください。
            
            テーマ: {target_keyword}
            
            【構成】
            1. 概要（{target_keyword}とは何か）
            2. 主な特徴やメリット
            3. 具体的な活用事例やコード例
            4. まとめ
            
            見出しは ## や ### を使ってください。
            商品リンク用のプレースホルダーなどは不要です。
            """
            
            logger.info("Generating content via Gemini...")
            generated_body = self._generate_text_with_gemini(prompt)
            
            if generated_body:
                self._save_article(dummy_url, title, generated_body, category)
            return

        # 在庫処理モード（今回は使いませんが残しておきます）
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            cursor.execute("SELECT url, title FROM products WHERE generated_body IS NULL LIMIT 1")
            row = cursor.fetchone()
            if row:
                current_url = row['url']
                current_title = row['title']
                prompt = f"トピック: {current_title} について解説記事を書いてください。"
                generated_body = self._generate_text_with_gemini(prompt)
                if generated_body:
                    self._save_article(current_url, current_title, generated_body, "Uncategorized")
        except Exception as e:
            logger.error(f"Error: {e}")
        finally:
            conn.close()

if __name__ == "__main__":
    generator = ContentGenerator(DB_PATH)