import google.generativeai as genai

# ==========================================
# ↓↓↓ ここにあなたのAPIキーを直接貼り付けてください ↓↓↓
api_key = "AIzaSyCPjA6Dtq_pi3jn4IPTU8_yuzqLBEp8xWk" 
# ↑↑↑ (例: "AIzaSyD...") クォート("")は消さないで！
# ==========================================

if api_key == "ここにAPIキーを貼り付ける":
    print("【エラー】APIキーが貼り付けられていません！コード内の『ここにAPIキーを貼り付ける』を書き換えてください。")
else:
    print("接続テスト中...")
    try:
        genai.configure(api_key=api_key)
        print("\n=== 利用可能なモデル一覧 ===")
        found = False
        for m in genai.list_models():
            if 'generateContent' in m.supported_generation_methods:
                print(f"- {m.name}")
                found = True
        
        if not found:
            print("生成可能なモデルが見つかりませんでした。")
        else:
            print("\n↑ このリストにある名前(例えば models/gemini-1.5-flash-001 など)を使えば必ず動きます！")

    except Exception as e:
        print(f"エラーが発生しました: {e}")