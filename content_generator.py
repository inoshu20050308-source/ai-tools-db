import os
import time
import sqlite3
import logging
from typing import List, Dict, Optional, Any
from dataclasses import dataclass

from dotenv import load_dotenv
import google.generativeai as genai
from google.api_core import exceptions as google_exceptions
from jinja2 import Template
from affiliate_manager import get_affiliate_html  # 広告管理モジュール

# ==========================================
# 0. Setup & Configuration
# ==========================================

# 環境変数の読み込み
load_dotenv()

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("gemini_generator.log", mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

@dataclass
class GeneratorConfig:
    db_path: str = "seo_content.db"
    model_name: str = "gemini-2.5-flash"
    api_key: str = os.getenv("GOOGLE_API_KEY")
    # Gemini Free Tier (15 RPM) 対策
    # 60秒 / 15回 = 4秒/回。安全マージンを含めて4.0秒待機する。
    request_interval_seconds: float = 4.0

# Jinja2 プロンプトテンプレート (Ver 2.0: Material for MkDocs Optimized)
PROMPT_TEMPLATE = """
あなたは「辛口だが信頼できるプロのテックレビュアー」です。
以下の製品データを元に、エンジニアやガジェット好きが唸る詳細なレビュー記事を作成してください。
出力は「Material for MkDocs」に最適化されたMarkdown形式で行います。

【製品データ】
- 製品名: {{ title }}
- 価格: {{ price }} 円
- 詳細: {{ description }}
- スペック: {{ specs }}

【記事構成と出力ルール】

1. **タイトル (h1)**
   - 検索意図を意識し、クリックしたくなる魅力的なタイトル（35文字以内）。

2. **総合スコア**
   - 記事の冒頭に、価格と性能のバランスから算出したスコアを `## 総合評価: ★★★★☆ (4.2/5.0)` の形式で記載。
   - その直下に、一言でいうとどういう製品か（要約）を記載。

3. **メリット・デメリット (最重要)**
   - 以下のAdmonition構文を必ず使用して出力すること。
   
   !!! success "この製品のメリット"
       - (メリット1)
       - (メリット2)
       - ...

   !!! failure "気になった点・デメリット"
       - (デメリット1)
       - (デメリット2)
       - ...

4. **詳細レビュー (h2)**
   - スペック表の羅列ではなく、実際の使用感を想像させる具体的な記述。
   - 専門用語を交えつつ、エンジニア視点での評価。

5. **スペック表 (h2)**
   - Markdownのテーブル形式で主要スペックを整理。

6. **結論 (h2)**
   - 「即買い」「セール待ち」「見送り」のいずれかを明言し、どんなユーザーにおすすめかを定義。

【禁止事項】
- 嘘の情報を書かない。不明な点は「不明」とする。
- 「いかがでしたか？」のような決まり文句は排除する。
"""

# ==========================================
# 1. Database Handler Class
# ==========================================
class DatabaseHandler:
    def __init__(self, db_path: str):
        self.db_path = db_path
        self._migrate_db()

    def _get_connection(self):
        return sqlite3.connect(self.db_path)

    def _migrate_db(self):
        """DBマイグレーション: generated_body カラムが存在しない場合に追加"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            cursor.execute("PRAGMA table_info(products)")
            columns = [info[1] for info in cursor.fetchall()]
            
            if "generated_body" not in columns:
                logger.info("Column 'generated_body' not found. Adding column...")
                cursor.execute("ALTER TABLE products ADD COLUMN generated_body TEXT")
                conn.commit()
            else:
                logger.debug("Column 'generated_body' already exists.")
        except Exception as e:
            logger.error(f"Migration failed: {e}")
        finally:
            conn.close()

    def fetch_pending_products(self, limit: int = 10) -> List[Dict[str, Any]]:
        """記事未生成のレコードを取得"""
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            # generated_body が NULL または 空文字 のものを対象とする
            query = """
            SELECT url, title, description, price, specs 
            FROM products 
            WHERE generated_body IS NULL OR generated_body = ''
            LIMIT ?
            """
            cursor.execute(query, (limit,))
            rows = cursor.fetchall()
            return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Failed to fetch data: {e}")
            return []
        finally:
            conn.close()

    def update_article(self, url: str, body: str):
        """生成記事を保存"""
        conn = self._get_connection()
        cursor = conn.cursor()
        try:
            query = """
            UPDATE products 
            SET generated_body = ?, updated_at = CURRENT_TIMESTAMP 
            WHERE url = ?
            """
            cursor.execute(query, (body, url))
            conn.commit()
            logger.info(f"Updated DB for: {url}")
        except Exception as e:
            logger.error(f"Failed to save article for {url}: {e}")
        finally:
            conn.close()

# ==========================================
# 2. Gemini Generator Class
# ==========================================
class GeminiGenerator:
    def __init__(self, config: GeneratorConfig):
        if not config.api_key:
            raise ValueError("Google API Key is missing. Check your .env file.")
        
        # Gemini API設定
        genai.configure(api_key=config.api_key)
        self.model = genai.GenerativeModel(config.model_name)
        self.config = config
        self.template = Template(PROMPT_TEMPLATE)

    def _build_prompt(self, product_data: Dict[str, Any]) -> str:
        return self.template.render(
            title=product_data.get('title', 'Unknown Product'),
            price=product_data.get('price', 'Unknown'),
            description=product_data.get('description', ''),
            specs=product_data.get('specs', '')
        )

    def generate_article(self, product_data: Dict[str, Any]) -> Optional[str]:
        """
        Gemini APIを使用して記事を生成する。
        レートリミット(15 RPM)を考慮し、実行後に必ず待機時間を設ける。
        """
        prompt = self._build_prompt(product_data)
        url = product_data.get('url')

        try:
            logger.info(f"Requesting Gemini for: {product_data.get('title')}...")
            
            # コンテンツ生成
            response = self.model.generate_content(prompt)
            
            # 安全のためテキスト取得前に検証
            if response.text:
                return response.text
            else:
                logger.warning(f"Gemini returned empty response for {url}")
                return None

        except google_exceptions.ResourceExhausted:
            logger.error(f"Rate limit exceeded (429) for {url}. Please increase sleep interval.")
            return None
        except Exception as e:
            logger.error(f"Generation error for {url}: {e}")
            return None
        finally:
            # 重要: Gemini Free Tier対策 (15 RPM = 4秒/req)
            # 成功・失敗に関わらず、APIを叩いたら必ず待機する
            wait_time = self.config.request_interval_seconds
            logger.info(f"Sleeping for {wait_time}s to respect rate limit...")
            time.sleep(wait_time)

# ==========================================
# 3. Main Execution Flow
# ==========================================
def main():
    logger.info("Starting Gemini Content Generator Pipeline...")

    # 設定と初期化
    config = GeneratorConfig()
    db = DatabaseHandler(config.db_path)
    generator = GeminiGenerator(config)

    # 1. 未処理データの取得 (テスト用に最大5件)
    pending_products = db.fetch_pending_products(limit=5)

    if not pending_products:
        logger.info("No pending products found.")
        return

    logger.info(f"Found {len(pending_products)} products to process.")

    # 2. 順次処理 (Rate Limitを守るため、あえて非同期にせずループで処理)
    for i, product in enumerate(pending_products, 1):
        logger.info(f"--- Processing {i}/{len(pending_products)}: {product.get('url')} ---")
        
        # 記事生成 (同期処理)
        generated_text = generator.generate_article(product)
        
        if generated_text:
            # --- 収益化ロジックの注入 ---
            # 製品タイトルに基づいて最適な広告HTMLを取得
            ad_html = get_affiliate_html(product['title'])
            
            # 記事本文の末尾に広告を結合
            final_content = generated_text + "\n\n" + ad_html
            # --------------------------

            # DB保存
            db.update_article(product['url'], final_content)
        else:
            logger.warning("Skipped DB update due to generation failure.")

    logger.info("Pipeline completed successfully.")

if __name__ == "__main__":
    main()