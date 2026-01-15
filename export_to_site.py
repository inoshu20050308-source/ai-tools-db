import sqlite3
import os
import shutil
import stat
import time
import logging

# 設定
DB_PATH = "seo_content.db"
SITE_DIR = "my_site"
DOCS_DIR = os.path.join(SITE_DIR, "docs")
TOOLS_DIR = os.path.join(DOCS_DIR, "tools")

# ログ設定
logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
logger = logging.getLogger(__name__)

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

def init_directories():
    """ディレクトリの初期化とクリーンアップ"""
    # toolsフォルダが存在する場合、中身を削除してリセット
    if os.path.exists(TOOLS_DIR):
        logger.info(f"Cleaning up old directory: {TOOLS_DIR}")
        try:
            # エラーハンドラを指定して削除
            shutil.rmtree(TOOLS_DIR, onerror=on_rm_error)
        except Exception as e:
            logger.error(f"Failed to clean directory (Process might be locking files): {e}")
            logger.info("Retrying in 2 seconds...")
            time.sleep(2)
            try:
                shutil.rmtree(TOOLS_DIR, ignore_errors=True)
            except:
                pass # 諦めて上書きに進む

    # ディレクトリ作成
    os.makedirs(TOOLS_DIR, exist_ok=True)
    
    # index.md がない場合は作成（トップページ用）
    index_path = os.path.join(DOCS_DIR, "index.md")
    if not os.path.exists(index_path):
        with open(index_path, "w", encoding="utf-8") as f:
            f.write("# Welcome to AI Tech Review\n\n左のメニューから記事をご覧ください。")

def export_articles():
    """DBから記事を読み出しMarkdownファイルとして書き出す"""
    init_directories()

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    try:
        # 記事本文があるものだけ取得
        cursor.execute("SELECT url, title, generated_body FROM products WHERE generated_body IS NOT NULL AND generated_body != ''")
        rows = cursor.fetchall()

        if not rows:
            logger.warning("No articles found in database to export.")
            return

        logger.info(f"Found {len(rows)} articles. Exporting...")

        for row in rows:
            url = row['url']
            title = row['title']
            body = row['generated_body']

            # ファイル名をURLから生成 (例: https://.../product-A -> product-A.md)
            # URLの最後の部分を取得。もし空なら適当なハッシュかIDを使う
            filename = url.strip("/").split("/")[-1]
            if not filename:
                filename = f"article_{hash(url)}"
            
            filename = f"{filename}.md"
            filepath = os.path.join(TOOLS_DIR, filename)

            # Markdown書き出し
            try:
                with open(filepath, "w", encoding="utf-8") as f:
                    # タイトルが本文に含まれていない場合のみヘッダー追加のロジックを入れても良いが
                    # 今回はAIがMarkdown全体を作っているのでそのまま書き出す
                    f.write(body)
                logger.info(f"Exported: {filename}")
            except Exception as e:
                logger.error(f"Failed to write {filename}: {e}")

    except Exception as e:
        logger.error(f"Database error: {e}")
    finally:
        conn.close()
        logger.info("Export completed.")

if __name__ == "__main__":
    export_articles()