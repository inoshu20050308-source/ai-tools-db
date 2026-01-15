import google.generativeai as genai
import os
from dotenv import load_dotenv

load_dotenv()
genai.configure(api_key=os.getenv("GOOGLE_API_KEY"))

print("=== あなたの環境で使えるモデル一覧 ===")
try:
    for m in genai.list_models():
        if 'generateContent' in m.supported_generation_methods:
            print(f"- {m.name}")
except Exception as e:
    print(f"エラーが発生しました: {e}")
    print("APIキーが正しいか、もう一度.envを確認してください。")