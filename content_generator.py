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

# 広告管理モジュールを読み込み
try:
    from affiliate_manager import get_affiliate_html
except ImportError:
    # モジュールがない場合のダミー
    def get_affiliate_html(title): return ""

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
    
    # 【修正】ユーザー環境で利用可能な最新モデル 'gemini-2.0-flash' に変更
    model_name: str = "gemini-2.0-flash"
    
    api_key: str = os.getenv("GOOGLE_API_KEY")
    
    # レート制限対策（設定維持）
    # 通常リクエスト間隔: 15秒 (4 RPM)
    request_interval_seconds: float = 15.0
    
    # エラー時のペナルティ待機時間: 30秒
    error_cooldown_seconds: float = 30.0

# Jinja2 プロンプトテンプレート (維持)
PROMPT_TEMPLATE = """
あなたは「辛口だが信頼できるプロのテック編集長」です。
提供された情報を元に、読者の購買意欲や知的好奇心を刺激する詳細なレビュー記事を作成してください。

【対象データ】
- 製品/トピック名: {{ title }}
- 価格/費用: {{ price }}
- 概要・詳細: {{ description }}
- スペック/仕様: {{ specs }}

【重要：ジャンル自動判定と執筆の視点】
まず、この対象が「物理ガジェット（ハードウェア）」か「ソフトウェア/AIツール」か「技術トレンド/ニュース」かを判断し、以下の視点で執筆してください。
- **ハードウェアの場合**: 質感、重量、バッテリー持ち、日常での使用感、競合機との物理的な違い。
- **ソフトウェア/AIの場合**: UI/UXの使いやすさ、処理速度、導入のしやすさ、課金する価値があるか。
- **ニュース/トレンドの場合**: 業界への影響、将来性、エンジニアが知っておくべき背景。

【記事構成ルール (Material for MkDocs形式)】

1. **タイトル (h1)**
   - 検索意図を意識し、35文字以内でクリックしたくなる魅力的なタイトルをつける。
   - （例: 「〇〇レビュー：神ツールか？それとも...」「〇〇が業界を揺るがす理由」）

2. **要約とスコア**
   - 記事冒頭に、忙しいエンジニア向けの3行要約を書く。
   - 製品レビューの場合は `## 総合評価: ★★★★☆ (4.5/5.0)` の形式でスコアをつける。ニュースの場合は不要。

3. **メリット・デメリット / 注目ポイント**
   - 以下のAdmonition構文を使用する。ニュースの場合は「Good/Bad」ではなく「注目点/懸念点」としてもよい。
   
   !!! success "Good: 注目すべきポイント"
       - (プロ視点でのメリット1)
       - (プロ視点でのメリット2)
       - ...

   !!! failure "Bad: 課題や注意点"
       - (忖度なしのデメリット1)
       - (デメリット2)
       - ...

4. **詳細レビュー/深掘り解説 (h2)**
   - スペックの羅列は禁止。「実際にどう役に立つか？」という視点で書く。
   - 専門用語を適切に使い、エンジニアの知的好奇心を満たす。

5. **スペック/データ表 (h2)**
   - Markdownテーブル形式で主要なデータを整理する。

6. **結論 (h2)**
   - 読者は「で、結局どうすればいい？」と思っている。
   - 「即ポチ推奨」「キャッチアップ必須」「様子見」など、具体的な行動を提案して締めくくる。

【禁止事項】
- 「いかがでしたか？」は禁止。
- 嘘の情報は書かない。
- AIツールやニュース記事に対して「物理的な重さ」や「質感」に言及しないこと。
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
        """DBマイグレーション"""
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
        """
        記事未生成のレコードを取得する。
        Gadgetカテゴリを最優先し、次に新しい順で取得する。
        """
        conn = self._get_connection()
        conn.row_factory = sqlite3.Row
        cursor = conn.cursor()
        try:
            # ORDER BY: category='Gadget' がTrue(1)のものを先頭にする
            query = """
            SELECT url, title, description, price, specs, category, scraped_at 
            FROM products 
            WHERE generated_body IS NULL OR generated_body = ''
            ORDER BY (category = 'Gadget') DESC, scraped_at DESC
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
        堅牢なレート制限対策（バックオフ）を含む。
        """
        prompt = self._build_prompt(product_data)
        url = product_data.get('url')
        title = product_data.get('title')

        try:
            logger.info(f"Requesting Gemini ({self.config.model_name}) for: {title} ...")
            
            # コンテンツ生成
            response = self.model.generate_content(prompt)
            
            if response.text:
                return response.text
            else:
                logger.warning(f"Gemini returned empty response for {url}")
                return None

        except google_exceptions.ResourceExhausted:
            # 429エラー時は長時間待機する
            cooldown = self.config.error_cooldown_seconds
            logger.error(f"!!! Rate limit exceeded (429) for {title}. !!!")
            logger.error(f"Entering COOL-DOWN mode for {cooldown} seconds...")
            
            # ペナルティ待機
            time.sleep(cooldown)
            
            # 今回はリトライせずスキップ（次回の実行に任せる）
            return None
        
        except google_exceptions.NotFound as e:
            # モデルが見つからないなどの404エラー
            logger.error(f"Model not found error: {e}")
            logger.error(f"Current model '{self.config.model_name}' might be invalid.")
            return None

        except Exception as e:
            logger.error(f"Generation error for {url}: {e}")
            return None
            
        finally:
            # 成功・失敗に関わらず、次のリクエストまで十分に間隔を空ける
            wait_time = self.config.request_interval_seconds
            logger.info(f"Sleeping for {wait_time}s to respect rate limit (Safe Interval)...")
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

    # 1. 未処理データの取得
    target_limit = 50
    logger.info(f"Fetching pending records (Limit: {target_limit}, Priority: Gadget)...")
    pending_products = db.fetch_pending_products(limit=target_limit)

    if not pending_products:
        logger.info("No pending products found.")
        return

    logger.info(f"Found {len(pending_products)} products to process.")

    # 2. 順次処理
    for i, product in enumerate(pending_products, 1):
        category = product.get('category', 'Unknown')
        logger.info(f"--- Processing {i}/{len(pending_products)} [{category}]: {product.get('url')} ---")
        
        # 記事生成
        generated_text = generator.generate_article(product)
        
        if generated_text:
            # 収益化ロジック
            ad_html = get_affiliate_html(product['title'])
            final_content = generated_text + "\n\n" + ad_html

            # DB保存
            db.update_article(product['url'], final_content)
        else:
            logger.warning("Skipped DB update due to generation failure (or rate limit skip).")

    logger.info("Pipeline completed successfully.")

if __name__ == "__main__":
    main()