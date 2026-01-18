import time
import logging
import subprocess
import os
import sys

# 自作モジュールのインポート
# content_generator.py と export_to_site.py が同階層にある前提
try:
    from content_generator import ContentGenerator, DB_PATH
    import export_to_site
except ImportError as e:
    print(f"Error importing modules: {e}")
    sys.exit(1)

# ==========================================
# 工場長の設定 (Configuration)
# ==========================================

# 今回生産する記事のキーワードリスト
TARGET_KEYWORDS = [
    "Python 業務効率化 ライブラリ",
    "Gemini API 使い方 Python",
    "VSCode おすすめ拡張機能 2025",
    "Docker 入門 初心者",
    "MkDocs Material カスタマイズ"
]

# ログ設定
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - [PIPELINE] - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler("pipeline.log", mode='a', encoding='utf-8')
    ]
)
logger = logging.getLogger(__name__)

def run_git_commands():
    """Gitコマンドを実行して変更をリモートにプッシュする"""
    commands = [
        ["git", "add", "."],
        ["git", "commit", "-m", "Auto-update: Generated new articles via Pipeline"],
        ["git", "push"]
    ]

    logger.info("Starting Git deployment...")
    
    for cmd in commands:
        try:
            result = subprocess.run(cmd, check=True, capture_output=True, text=True)
            logger.info(f"Executed: {' '.join(cmd)}")
            if result.stdout:
                logger.debug(result.stdout)
        except subprocess.CalledProcessError as e:
            logger.error(f"Git Error on command {' '.join(cmd)}: {e.stderr}")
            # commitは変更がない場合にエラーになることがあるが、パイプライン自体は止めない
            if "nothing to commit" in e.stderr or "clean" in e.stderr:
                logger.info("Nothing to commit. Continuing.")
            else:
                logger.warning("Git command failed, but proceeding.")

def main():
    logger.info("=== SEO Content Pipeline Started ===")
    
    generator = ContentGenerator(DB_PATH)
    
    # -------------------------------------------------
    # 1. 記事の連続生成 (Production Phase)
    # -------------------------------------------------
    logger.info(f"Target Keywords: {len(TARGET_KEYWORDS)} items")
    
    for i, keyword in enumerate(TARGET_KEYWORDS, 1):
        logger.info(f"Processing [{i}/{len(TARGET_KEYWORDS)}]: {keyword}")
        
        try:
            # キーワード指定で記事生成を実行
            generator.generate_article(target_keyword=keyword)
            
            # APIレートリミット対策（10秒待機）
            logger.info("Sleeping for 10s to respect API limits...")
            time.sleep(10)
            
        except Exception as e:
            logger.error(f"Failed to generate article for '{keyword}': {e}")
            continue

    logger.info("All articles generation phase completed.")

    # -------------------------------------------------
    # 2. サイトへの反映 (Export Phase)
    # -------------------------------------------------
    logger.info("Exporting content to MkDocs site...")
    try:
        # export_to_site.py のメイン関数を実行
        export_to_site.export_articles()
        logger.info("Export completed successfully.")
    except Exception as e:
        logger.critical(f"Export failed: {e}")
        return # サイト生成に失敗したらデプロイはしない

    # -------------------------------------------------
    # 3. 公開 (Deployment Phase)
    # -------------------------------------------------
    # MkDocsのビルドコマンドが必要ならここで実行（GitHub Pagesならpushだけで良い場合も）
    # subprocess.run(["mkdocs", "build"], check=True) 
    
    # Git Push
    run_git_commands()

    logger.info("=== SEO Pipeline Finished Successfully ===")

if __name__ == "__main__":
    main()