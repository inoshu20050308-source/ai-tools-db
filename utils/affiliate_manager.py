"""
アフィリエイトリンクを一元管理するファイル
"""

# ==========================================
# 1. ここにあなたのA8.netリンクを登録します
# ==========================================

# 特定の商品専用のリンク（辞書形式）
SPECIFIC_LINKS = {
    "PLAUD": """
    <a href="https://px.a8.net/svt/ejp?a8mat=4AV789+1JYRN6+5J4W+5YZ76" rel="nofollow">PLAUD NOTE</a>
    <img border="0" width="1" height="1" src="https://www14.a8.net/0.gif?a8mat=4AV789+1JYRN6+5J4W+5YZ76" alt="">
    """,
    
    # 必要ならここに追加（例： "Notion": "NotionのリンクHTML",）
}

# 全記事に表示するデフォルト広告（2つ目の画像バナーを使用）
DEFAULT_AD = """
<div style="margin-top: 30px; padding: 20px; background: #f8f9fa; border-radius: 8px; text-align: center;">
    <p style="font-weight: bold; margin-bottom: 10px;">▼ 管理人おすすめ ▼</p>
    <a href="https://px.a8.net/svt/ejp?a8mat=4AV789+1NJD9U+1WP2+6DZBL" rel="nofollow">
    <img border="0" width="120" height="90" alt="" src="https://www25.a8.net/svt/bgt?aid=260116569100&wid=001&eno=01&mid=s00000008903001073000&mc=1"></a>
    <img border="0" width="1" height="1" src="https://www11.a8.net/0.gif?a8mat=4AV789+1NJD9U+1WP2+6DZBL" alt="">
</div>
"""

# ==========================================
# 2. リンク取得ロジック
# ==========================================

def get_affiliate_html(product_title: str) -> str:
    """
    記事のタイトル（製品名）にマッチする広告があればそれを返し、
    なければデフォルト広告を返す関数
    """
    # 特定の商品リンクがあるかチェック
    for keyword, html in SPECIFIC_LINKS.items():
        if keyword.lower() in product_title.lower():
            # マッチしたら、その商品のリンク + デフォルトバナーも返す（収益最大化）
            return f'<div class="affiliate-box"><p>公式サイトはこちら：{html}</p></div>'

    # マッチングしない場合はデフォルト広告のみ返す
    return DEFAULT_AD