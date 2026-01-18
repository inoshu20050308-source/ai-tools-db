import time
import logging
import subprocess
import sys
from typing import List

# ★修正点1: クラスと設定値を明示的にインポート
from content_generator import ContentGenerator, DB_PATH

# ==========================================
# デフォルトのキーワードリスト
# ==========================================
DEFAULT_KEYWORDS = [
    "Python 副業 稼ぎ方",
    "Gemini API 活用事例",
]

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(levelname)s - %(message)s',
    handlers=[logging.StreamHandler()]
)
logger = logging.getLogger(__name__)

def git_push_changes(count):
    """生成された記事をGitHubにプッシュして公開する"""
    try:
        logger.info("🚀 Git送信を開始します...")
        subprocess.run(["git", "add", "."], check=True)
        commit_message = f"Auto-generated articles: {count} items"
        subprocess.run(["git", "commit", "-m", commit_message], check=True)
        subprocess.run(["git", "push"], check=True)
        logger.info("✅ GitHubへの送信が完了しました！サイトが更新されます。")
    except Exception as e:
        logger.error(f"❌ Git操作エラー: {e}")

def run_factory():
    """記事量産工場のメインプロセス"""
    
    # コマンド引数のチェック
    if len(sys.argv) > 1:
        target_list = sys.argv[1:]
        logger.info(f"🎯 コマンドライン引数を検出しました: {target_list}")
    else:
        target_list = DEFAULT_KEYWORDS
        logger.info("📂 コマンド指定がないため、ファイル内のデフォルトリストを使用します。")

    logger.info("🏭 記事量産工場を稼働させます...")
    
    # ★修正点2: ここで「記事作成ロボ」を実体化（起動）させます
    generator = ContentGenerator(DB_PATH)
    
    total = len(target_list)
    
    for i, keyword in enumerate(target_list, 1):
        logger.info(f"--- [{i}/{total}] キーワード: '{keyword}' の記事を作成中 ---")
        try:
            # ★修正点3: 実体化したロボットに命令する
            generator.generate_article(target_keyword=keyword)
            
            logger.info(f"✨ '{keyword}' の記事作成完了")
            
            if i < total:
                logger.info("☕ API休憩中 (10秒)...")
                time.sleep(10)
        except Exception as e:
            logger.error(f"⚠️ '{keyword}' の作成に失敗しました: {e}")
            continue

    logger.info("📝 全記事の生成が終了しました。サイトデータを更新します。")
    
    # ★修正点4: エラー回避のため、コマンド経由でサイト生成を実行
    try:
        subprocess.run(["python", "export_to_site.py"], check=True)
    except Exception as e:
        logger.error(f"❌ サイト生成エラー: {e}")
        return

    # Gitへ送信
    git_push_changes(total)
    logger.info("🎉 全工程が完了しました。")

if __name__ == "__main__":
    run_factory()