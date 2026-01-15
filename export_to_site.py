import sqlite3
import os
import shutil
import logging

# 設定
DB_PATH = "seo_content.db"
SITE_DIR = "my_site"
DOCS_DIR = os.path.join(SITE_DIR, "docs")
TOOLS_DIR = os.path.join(DOCS_DIR, "tools")

logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(message)s')

def init_directories():
    """フォルダの初期化"""
    if os.path.exists(TOOLS_DIR):
        shutil.rmtree(TOOLS_DIR) # 古い記事を一旦消す
    os.makedirs(TOOLS_DIR)
    logging.info(f"Initialized directory: {TOOLS_DIR}")

def create_index_page(products):
    """トップページ（index.md）にツール一覧リンクを生成"""
    index_path = os.path.join(DOCS_DIR, "index.md")
    
    content = """# AIツールデータベース

最新のAIツールやガジェットのスペック・レビューをまとめています。

## 記事一覧
"""
    for p in products:
        # ファイル名はURLの末尾を使う（例: tools/chatgpt）
        filename = p['url'].rstrip('/').split('/')[-1]
        title = p['title']
        content += f"- [{title}](tools/{filename}.md)\n"

    with open(index_path, "w", encoding="utf-8") as f:
        f.write(content)
    logging.info("Updated index.md")

def export_articles():
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()
    
    # 記事生成済みのデータのみ取得
    cursor.execute("SELECT * FROM products WHERE generated_body IS NOT NULL AND generated_body != ''")
    products = cursor.fetchall()
    
    if not products:
        logging.warning("No articles found in DB. Run content_generator.py first!")
        return

    init_directories()

    for p in products:
        # URLからファイル名を決定
        filename = p['url'].rstrip('/').split('/')[-1] + ".md"
        filepath = os.path.join(TOOLS_DIR, filename)
        
        # 記事の中身（Markdown）
        # MkDocs用にメタデータ（Frontmatter）を付けると尚良いが、今回はシンプルに本文のみ
        body = p['generated_body']
        
        with open(filepath, "w", encoding="utf-8") as f:
            f.write(body)
        
        logging.info(f"Exported: {filename}")

    # インデックスページも更新
    create_index_page(products)
    conn.close()
    logging.info(f"Export completed! Total {len(products)} articles.")

if __name__ == "__main__":
    export_articles()