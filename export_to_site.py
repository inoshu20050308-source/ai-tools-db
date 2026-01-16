import sqlite3
import os
import shutil
import stat
import time
import logging
from collections import defaultdict

# ==========================================
# 設定 & パス定義
# ==========================================
DB_PATH = "seo_content.db"
SITE_DIR = "my_site"
DOCS_DIR = os.path.join(SITE_DIR, "docs")
TOOLS_DIR = os.path.join(DOCS_DIR, "tools")

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

# ==========================================
# ユーティリティ関数
# ==========================================
def on_rm_error(func, path, exc_info):
    """
    Windowsで削除に失敗した場合（読み取り専用など）、
    属性を変更して再試行するためのエラーハンドラ
    """
    try:
        os.chmod(path, stat.S_IWRITE)
        func(path)
    except Exception as e:
        logger.warning(f"Could not remove {path}: {e}")

def safe_filename(url: str) -> str:
    """URLから安全なファイル名を生成する"""
    # 末尾のスラッシュを除去して最後のセグメントを取得
    name = url.strip("/").split("/")[-1]
    
    # もし名前が取得できない、あるいは短すぎる場合はハッシュ値を使う
    if not name or len(name) < 2:
        name = f"article_{abs(hash(url))}"
    
    # 拡張子 .html などが含まれていたら除去して .md にする
    if "." in name:
        name = name.split(".")[0]
        
    return f"{name}.md"

def init_directories():
    """記事格納用ディレクトリ(tools)の初期化"""
    if os.path.exists(TOOLS_DIR):
        logger.info(f"Cleaning up old directory: {TOOLS_DIR}")
        try:
            shutil.rmtree(TOOLS_DIR, onerror=on_rm_error)
        except Exception as e:
            logger.error(f"Failed to clean directory: {e}")
            time.sleep(1)
            try:
                shutil.rmtree(TOOLS_DIR, ignore_errors=True)
            except:
                pass

    os.makedirs(TOOLS_DIR, exist_ok=True)

# ==========================================
# メイン処理
# ==========================================
def export_articles():
    """DBから記事を読み出し、カテゴリごとに整理して書き出す"""
    init_directories()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    # カテゴリごとの記事リストを保持する辞書
    # キー: カテゴリ名, 値: 記事情報のリスト
    categorized_articles = defaultdict(list)

    try:
        # 1. 記事データの取得 (categoryカラムも含める)
        # categoryカラムがない古いDBの場合のエラー回避のため、try-exceptでカラム確認しても良いが
        # 前回のパイプライン修正でMigrationが入っている前提とする。
        try:
            query = "SELECT url, title, generated_body, category FROM products WHERE generated_body IS NOT NULL AND generated_body != ''"
            cursor.execute(query)
        except sqlite3.OperationalError:
            # 万が一 category カラムがない場合へのフォールバック
            logger.warning("'category' column missing. Fetching without category.")
            query = "SELECT url, title, generated_body, 'Uncategorized' as category FROM products WHERE generated_body IS NOT NULL AND generated_body != ''"
            cursor.execute(query)

        rows = cursor.fetchall()

        if not rows:
            logger.warning("No articles found in database to export.")
            return

        logger.info(f"Found {len(rows)} articles. Exporting...")

        # 2. 個別記事ファイル(.md)の生成
        for row in rows:
            url = row['url']
            title = row['title']
            body = row['generated_body']
            # DBにカテゴリがない場合(None)は 'Uncategorized' とする
            category = row['category'] if row['category'] else 'Uncategorized'

            filename = safe_filename(url)
            filepath = os.path.join(TOOLS_DIR, filename)

            # 記事書き出し
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    f.write(body)
                
                # インデックス作成用にメタデータを保存
                categorized_articles[category].append({
                    "title": title,
                    "path": f"tools/{filename}" # index.md から見た相対パス
                })
                
                logger.info(f"Exported [{category}]: {filename}")
            except Exception as e:
                logger.error(f"Failed to write {filename}: {e}")

        # 3. トップページ (index.md) の生成
        create_index_page(categorized_articles)

    except Exception as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()
        logger.info("Export process completed.")

def create_index_page(categorized_articles):
    """カテゴリ分けされた記事リストから index.md を生成する"""
    index_path = os.path.join(DOCS_DIR, "index.md")
    
    logger.info("Generating index.md...")

    with open(index_path, "w", encoding="utf-8") as f:
        # サイトヘッダー
        f.write("# AI Tech Review\n\n")
        f.write("最新のAIツール、技術トレンド、ガジェット情報を網羅するデータベースです。\n\n")

        # セクション1: ガジェット (Gadget)
        if "Gadget" in categorized_articles and categorized_articles["Gadget"]:
            f.write("## 🏆 最新ガジェットランキング (Gadget)\n\n")
            f.write("価格.comや楽天のランキングから厳選した注目ガジェット。\n\n")
            for article in categorized_articles["Gadget"]:
                f.write(f"- [{article['title']}]({article['path']})\n")
            f.write("\n")

        # セクション2: 技術ニュース (Tech News)
        if "Tech News" in categorized_articles and categorized_articles["Tech News"]:
            f.write("## 📰 技術トレンドニュース (Tech News)\n\n")
            f.write("Zennなどの技術メディアで話題のトピックを解説。\n\n")
            for article in categorized_articles["Tech News"]:
                f.write(f"- [{article['title']}]({article['path']})\n")
            f.write("\n")

        # セクション3: AIツール (AI Tool)
        if "AI Tool" in categorized_articles and categorized_articles["AI Tool"]:
            f.write("## 🤖 AIツールデータベース (AI Tool)\n\n")
            f.write("業務効率化に役立つ最新AIツールのレビュー。\n\n")
            for article in categorized_articles["AI Tool"]:
                f.write(f"- [{article['title']}]({article['path']})\n")
            f.write("\n")
            
        # その他 (Uncategorized)
        if "Uncategorized" in categorized_articles and categorized_articles["Uncategorized"]:
            f.write("## 📁 その他\n\n")
            for article in categorized_articles["Uncategorized"]:
                f.write(f"- [{article['title']}]({article['path']})\n")
            f.write("\n")

    logger.info("index.md updated successfully.")

if __name__ == "__main__":
    export_articles()