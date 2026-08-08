#!/usr/bin/env python3
"""
くらしのものさし 自動化スクリプト

3つのタスクをコマンドライン引数で切り替えて実行する。
  python run_task.py genre     -> ジャンル抽出（柱1）
  python run_task.py article   -> 比較記事生成（柱2）
  python run_task.py pinterest -> Pinterest投稿案生成（柱3）

必要な環境変数:
  ANTHROPIC_API_KEY  Claude APIキー（GitHub Secretsから渡す）
"""

import os
import re
import sys
import json
import glob
import datetime
from pathlib import Path

import anthropic

MODEL = "claude-sonnet-5"
MAX_TOKENS = 8000

ROOT = Path(__file__).resolve().parent.parent
SITE_DIR = ROOT / "site"
ARTICLES_DIR = SITE_DIR / "articles"
GENRES_DIR = ROOT / "genres"
PINTEREST_DIR = ROOT / "pinterest"
POOL_FILE = GENRES_DIR / "pool.json"

client = anthropic.Anthropic()  # ANTHROPIC_API_KEY を環境変数から自動取得


def call_claude(prompt: str) -> str:
    """Claude APIを呼び出してテキスト応答を返す"""
    message = client.messages.create(
        model=MODEL,
        max_tokens=MAX_TOKENS,
        messages=[{"role": "user", "content": prompt}],
    )
    return "".join(block.text for block in message.content if block.type == "text")


def load_pool() -> list:
    if POOL_FILE.exists():
        return json.loads(POOL_FILE.read_text(encoding="utf-8"))
    return []


def save_pool(pool: list) -> None:
    GENRES_DIR.mkdir(parents=True, exist_ok=True)
    POOL_FILE.write_text(
        json.dumps(pool, ensure_ascii=False, indent=2), encoding="utf-8"
    )


# ---------------------------------------------------------------------------
# タスク1: ジャンル抽出
# ---------------------------------------------------------------------------
def task_genre() -> None:
    existing_names = [g["name"] for g in load_pool()]
    existing_note = (
        f"\n\n既存ジャンル（重複させないこと）: {', '.join(existing_names)}"
        if existing_names
        else ""
    )

    prompt = f"""あなたは楽天市場に詳しいアフィリエイトリサーチャーです。
次の条件をすべて満たす商品ジャンルを15個リストアップしてください。
1. 消耗品または定期的に買い替えが発生する日用品であること
2. 季節による需要の変動が小さいこと
3. 比較して選びたくなる程度に商品数が多いこと
4. 価格帯が1,500円から8,000円であること
5. 実際に使ってみないと分からない差があること
各ジャンルについて、次を出してください。
・ジャンル名
・想定される検索キーワードを3つ
・買い替えの頻度
・比較記事にしたときの切り口
・このジャンルで比較すべき項目を4つ
・同時に買われやすい関連商品を2つ
表形式で出力してください。
高単価より、買い替え頻度が高いものを優先してください。{existing_note}

最後に、上記15個のジャンル名だけを ```json ["ジャンル名1", "ジャンル名2", ...] ``` の形式でコードブロックにまとめて出力してください。"""

    result = call_claude(prompt)

    # 記録用にMarkdownを保存
    GENRES_DIR.mkdir(parents=True, exist_ok=True)
    today = datetime.date.today().isoformat()
    (GENRES_DIR / f"genres_{today}.md").write_text(result, encoding="utf-8")

    # JSONブロックを抜き出してpoolに追加
    match = re.search(r"```json\s*(\[.*?\])\s*```", result, re.DOTALL)
    pool = load_pool()
    existing = {g["name"] for g in pool}
    if match:
        try:
            names = json.loads(match.group(1))
            for name in names:
                if name not in existing:
                    pool.append({"name": name, "status": "pending"})
        except json.JSONDecodeError:
            print("警告: JSON抽出に失敗しました。手動でpool.jsonを確認してください。")
    save_pool(pool)
    print(f"ジャンル抽出完了。pool.json に {len(pool)} 件登録済み。")


# ---------------------------------------------------------------------------
# タスク2: 比較記事生成
# ---------------------------------------------------------------------------
def slugify(name: str) -> str:
    # 日本語ジャンル名から簡易スラッグを作る（ローマ字化はしない、連番で衝突回避）
    base = re.sub(r"[^\w\-]", "", name.replace(" ", "-"))
    return base or "genre"


def task_article() -> None:
    pool = load_pool()
    pending = [g for g in pool if g["status"] == "pending"]
    if not pending:
        print("記事化待ちのジャンルがありません。先に genre タスクを実行してください。")
        return

    genre = pending[0]
    genre_name = genre["name"]

    prompt = f"""あなたは実際にその商品を使って記事を書く、経験5年のレビュアーです。
次のジャンルについて、実在する商品5〜7点を挙げ、比較記事を書いてください。

ジャンル：{genre_name}
比較する商品：5〜7点（実在する商品名を使うこと）
想定読者：このジャンルで買い替えに悩んでいる人
狙うキーワード：{genre_name} おすすめ
分量：3,000字前後

構成
1. 読者がいま困っている場面の描写
2. この記事が向いていない人(先に外す)
3. 選ぶときに見るべき基準を3つ
4. 比較表
5. 商品ごとのレビュー(良い点・気になる点・向いている人)
6. 使い方別のおすすめ
7. まとめ

ルール
・すべての商品を良いと書かないこと。合わない場面を必ず書くこと
・数字と具体的な使用場面を入れること
・「絶対」「必ず」「誰でも」の保証表現は使わないこと
・効果や結果の断定はしないこと
・他社製品を貶める表現は使わないこと
・楽天アフィリエイトリンクはまだ無いので、商品名はリンクなしのプレーンテキストで書くこと

出力は本文のみをMarkdownで書いてください（前置きや説明文は不要です）。"""

    body_markdown = call_claude(prompt)

    slug = slugify(genre_name)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{slug}.md"
    out_path.write_text(body_markdown, encoding="utf-8")

    # poolのステータス更新
    for g in pool:
        if g["name"] == genre_name:
            g["status"] = "done"
            g["article_path"] = str(out_path.relative_to(ROOT))
    save_pool(pool)

    print(f"記事生成完了: {out_path}")
    print("※ 比較表・商品カードへのアフィリエイトリンク埋め込みは、これまで通り手動での確認作業が必要です。")


# ---------------------------------------------------------------------------
# タスク3: Pinterest投稿案生成
# ---------------------------------------------------------------------------
def task_pinterest() -> None:
    md_files = sorted(ARTICLES_DIR.glob("*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not md_files:
        print("記事が見つかりません。先に article タスクを実行してください。")
        return

    latest = md_files[0]
    title_line = latest.read_text(encoding="utf-8").splitlines()[0].lstrip("# ").strip()

    prompt = f"""次の記事をもとに、Pinterestの投稿案を10本作ってください。
記事タイトル：{title_line}
記事URL：（公開後に手動で追記してください）
想定読者：このジャンルで買い替えに悩んでいる人

各案について、次を出してください。
・ピンのタイトル(全角20文字以内、検索されそうな言葉を入れる)
・説明文(200文字以内、キーワードを自然に含める)
・画像に載せる文字(2行以内)
・おすすめの配色と構図
・保存されやすいボードの想定
・投稿する曜日と時間帯の目安

表形式で出力してください。煽り表現は使わず、選ぶ手助けになる書き方にしてください。
出力の最後に、公開当日に投稿する3本と、残り7本を1週間で分散投稿するスケジュール案を添えてください。"""

    result = call_claude(prompt)

    PINTEREST_DIR.mkdir(parents=True, exist_ok=True)
    out_path = PINTEREST_DIR / f"{latest.stem}_pinterest.md"
    out_path.write_text(result, encoding="utf-8")
    print(f"Pinterest投稿案生成完了: {out_path}")


# ---------------------------------------------------------------------------
TASKS = {
    "genre": task_genre,
    "article": task_article,
    "pinterest": task_pinterest,
}


def main() -> None:
    if len(sys.argv) != 2 or sys.argv[1] not in TASKS:
        print(f"使い方: python {sys.argv[0]} [{'|'.join(TASKS)}]")
        sys.exit(1)
    TASKS[sys.argv[1]]()


if __name__ == "__main__":
    main()
