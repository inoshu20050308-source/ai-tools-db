from playwright.sync_api import sync_playwright
import time

def save_cookies():
    with sync_playwright() as p:
        # ブラウザを起動（ログインできるように画面を表示）
        browser = p.chromium.launch(headless=False)
        context = browser.new_context()
        page = context.new_page()

        print("🔵 Xのログイン画面を開きます。")
        print("❗ 自分でIDとパスワードを入力してログインしてください！")
        print("❗ ログインが完了してホーム画面（タイムライン）が表示されるまで操作してください。")
        
        page.goto("https://x.com/i/flow/login")

        # ログイン完了を待つ（URLが 'home' になるまで、最大3分待機）
        try:
            page.wait_for_url("**/home", timeout=180000)
            print("✅ ログインを検知しました！")
        except:
            print("❌ タイムアウトしました。ログインできませんでしたか？")
            return

        # ログイン状態（クッキー）をファイルに保存
        context.storage_state(path="x_cookies.json")
        print("💾 ログイン情報（合鍵）を 'x_cookies.json' に保存しました。")
        print("✨ これでもうID入力は不要です！")
        
        time.sleep(2)
        browser.close()

if __name__ == "__main__":
    save_cookies()