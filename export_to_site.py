import sqlite3
import os
import shutil
import urllib.parse

# 設定
DB_PATH = "seo_content.db"
DOCS_DIR = "docs"
# 記事を格納するサブフォルダ（整理用）
ARTICLES_DIR = os.path.join(DOCS_DIR, "articles")

def get_db_connection():
    return sqlite3.connect(DB_PATH)

def init_docs_structure():
    """フォルダ構造の初期化"""
    os.makedirs(ARTICLES_DIR, exist_ok=True)

def create_search_buttons_md(title):
    """記事末尾の検索ボタンMarkdownを作成"""
    encoded_title = urllib.parse.quote(title)
    amazon_url = f"https://www.amazon.co.jp/s?k={encoded_title}"
    rakuten_url = f"https://search.rakuten.co.jp/search/mall/{encoded_title}"
    yahoo_url = f"https://shopping.yahoo.co.jp/search?p={encoded_title}"

    return f"""
## 🛍️ この商品をさがす
<div class="grid cards" markdown>
-   [:material-cart: Amazonで探す]({amazon_url})
-   [:material-store: 楽天市場で探す]({rakuten_url})
-   [:material-shopping: Yahoo!で探す]({yahoo_url})
</div>
"""

def update_index_page(articles):
    """トップページ(index.md)に新着記事リストを書き込む"""
    index_path = os.path.join(DOCS_DIR, "index.md")
    
    # トップページの固定ヘッダー部分
    header = """# AI Tools & Gadget DB
ようこそ。ここはAIによって自動生成されたガジェット・ツール情報データベースです。

## 🆕 新着記事一覧
"""
    
    with open(index_path, "w", encoding="utf-8") as f:
        f.write(header)
        
        # 新しい順にリンクを書き込む
        # articles は (filename, title, category) のリスト想定
        for filename, title, category in articles:
            # リンク先は articles/filename
            link = f"articles/{filename}"
            f.write(f"- [{title}]({link}) <small>({category})</small>\n")

def export_article_to_markdown():
    """DBから記事を読み出し、MDファイル生成 ＆ index.md更新"""
    init_docs_structure()
    conn = get_db_connection()
    conn.row_factory = sqlite3.Row
    cursor = conn.cursor()

    cursor.execute("SELECT * FROM products ORDER BY scraped_at DESC")
    rows = cursor.fetchall()

    exported_articles = []

    for row in rows:
        title = row["title"]
        body = row["generated_body"]
        category = row["category"]
        
        # ファイル名をURLハッシュやIDから決定（なければタイトルから適当に）
        # ここでは簡易的にurlのハッシュ値の一部を使うか、既存ロジックに合わせる
        # DBにurlがある前提
        url_hash = row["url"].split("/")[-1].replace(".html", "")
        if not url_hash:
             # 万が一ハッシュがない場合のバックアップ
             import hashlib
             url_hash = hashlib.md5(row["url"].encode()).hexdigest()
             
        filename = f"{url_hash}.md"
        filepath = os.path.join(ARTICLES_DIR, filename)

        # 本文がない場合はスキップ
        if not body:
            continue

        # 検索ボタンを追加
        search_buttons = create_search_buttons_md(title)
        
        full_content = f"# {title}\n\n{body}\n\n{search_buttons}"

        with open(filepath, "w", encoding="utf-8") as f:
            f.write(full_content)
        
        print(f"Exported: {filename}")
        exported_articles.append((filename, title, category))

    # 最後にトップページを更新
    update_index_page(exported_articles)
    print("✅ index.md has been updated with new articles.")

    conn.close()

def main():
    export_article_to_markdown()

if __name__ == "__main__":
    main()