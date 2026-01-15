import sqlite3

# DB接続
conn = sqlite3.connect("seo_content.db")
cursor = conn.cursor()

# 記事が生成されたレコードを取得
cursor.execute("SELECT title, generated_body FROM products WHERE generated_body IS NOT NULL LIMIT 1")
row = cursor.fetchone()

conn.close()

if row:
    print(f"\n=== タイトル: {row[0]} ===\n")
    print(row[1])
    print("\n" + "="*30 + "\n")
    print("✅ 記事の生成に成功しています！")
else:
    print("⚠️ まだ記事が生成されていません。content_generator.py を実行してください。")