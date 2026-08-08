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
    replace_freq = genre.get("frequency", "")

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
・楽天アフィリエイトリンクはまだ無いので、商品名はリンクなしのプレーンテキストで書くこと（<a>タグや画像タグは使わないこと）

出力形式は、次のHTML構造・CSSクラス名に厳密に合わせて、記事本文のHTMLフラグメントのみを出力してください（前置き・説明・```html のようなコードフェンスは一切不要です）。

<article class="article-body">
  <h2>読者がいま困っている場面</h2>
  <p>...</p>
  <h2>この記事が向いていない人</h2>
  <div class="callout warn"><strong>先に外しておきます</strong>...</div>
  <ul><li>...</li></ul>
  <h2>選ぶときに見るべき基準3つ</h2>
  <h3>① ...</h3><p>...</p>
  <h3>② ...</h3><p>...</p>
  <h3>③ ...</h3><p>...</p>
  <h2>比較表</h2>
  <div class="table-wrap"><table><thead><tr><th>商品名</th><th class="num">参考価格</th><th>...</th><th>...</th><th>...</th><th class="num">...単価目安</th></tr></thead><tbody>
    <tr><td>...</td><td class="num">...円</td><td>...</td><td>...</td><td>...</td><td class="num">...</td></tr>
  </tbody></table></div>
  <h2>商品ごとのレビュー</h2>
  <div class="product-card">
    <h3>商品名</h3>
    <p class="voice">一言コメント（任意）</p>
    <div class="pc-grid">
      <div class="pc-good"><div class="h">良い点</div>...</div>
      <div class="pc-caution"><div class="h">気になる点</div>...</div>
    </div>
    <p style="margin-top:14px; font-size:.88rem; color:var(--ink-soft);"><strong>向いている人：</strong>...</p>
  </div>
  （商品カードを商品数ぶん繰り返す）
  <h2>使い方別のおすすめ</h2>
  <ul><li><strong>...：</strong>...</li></ul>
  <h2>まとめ</h2>
  <p>...</p>
  <div class="callout" style="margin-top:40px;"><strong>広告表記</strong>本記事にはアフィリエイトリンク（PR）が含まれます。紹介した商品は実際に購入・使用した上で記載しており、感想には個人差があります。</div>
</article>

また、出力の最後に、以下のメタ情報を ```json ``` のコードブロックで必ず付けてください（記事本文には含めない）。
```json
{{
  "title": "記事タイトル（32文字程度）",
  "description": "meta description用の1文（80文字程度）",
  "price_range": "例: 680円〜2,178円",
  "product_count": 6,
  "read_minutes": 7,
  "frequency": "{genre_name}の一般的な買い替え頻度（例: 1〜2ヶ月）"
}}
```"""

    result = call_claude(prompt)

    # メタ情報JSONを抽出
    match = re.search(r"```json\s*(\{.*?\})\s*```", result, re.DOTALL)
    meta = {}
    if match:
        try:
            meta = json.loads(match.group(1))
        except json.JSONDecodeError:
            print("警告: メタ情報のJSON抽出に失敗しました。")
    article_html = result[: match.start()].strip() if match else result.strip()

    slug = slugify(genre_name)
    ARTICLES_DIR.mkdir(parents=True, exist_ok=True)
    out_path = ARTICLES_DIR / f"{slug}.html"

    title = meta.get("title", genre_name + "比較")
    description = meta.get("description", f"{genre_name}を実際に使って比較しました。")

    full_page = f"""<!DOCTYPE html>
<html lang="ja">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}｜くらしのものさし</title>
<meta name="description" content="{description}">
<link rel="stylesheet" href="../style.css">
</head>
<body>

<header class="site-header">
  <div class="wrap">
    <div class="brand">
      <span class="brand-mark"><a href="../index.html" style="color:inherit;">くらしのものさし</a></span>
      <span class="brand-tag">日用品・消耗品 比較記録</span>
    </div>
    <nav class="site-nav">
      <a href="../index.html#featured">比較記事</a>
      <a href="../index.html#genres">ジャンル一覧</a>
      <a href="../index.html#method">選び方の基準</a>
      <a href="../about.html">運営者情報</a>
    </nav>
  </div>
</header>

<div class="article-head">
  <div class="wrap">
    <div class="breadcrumb"><a href="../index.html">トップ</a> ／ <a href="../index.html#genres">{genre_name}</a> ／ 比較記事</div>
    <span class="tag-pr">PR / 比較レビュー</span>
    <h1>{title}</h1>
    <p class="article-lede">{description}</p>
  </div>
</div>

<div class="article-body">
{article_html}
</div>

<footer class="site-footer">
  <div class="wrap">
    <div>くらしのものさし — 日用品・消耗品の比較記録</div>
    <div class="disclosure">
      本サイトの記事内には、楽天アフィリエイトを含むアフィリエイトプログラムによる広告リンク（PR）が含まれます。感想には個人差があり、効果・効能を保証するものではありません。<br>
      詳しくは<a href="../about.html">運営者情報・サイトポリシー</a>をご覧ください。
    </div>
  </div>
</footer>

</body>
</html>
"""
    out_path.write_text(full_page, encoding="utf-8")

    # index.htmlへ自動追記
    update_index_html(genre_name, slug, title, description, meta)

    # poolのステータス更新
    for g in pool:
        if g["name"] == genre_name:
            g["status"] = "done"
            g["article_path"] = str(out_path.relative_to(ROOT))
    save_pool(pool)

    print(f"記事生成完了: {out_path}")
    print("※ アフィリエイトリンクの取得・埋め込みはこれまで通り手動確認が必要です。")


def update_index_html(genre_name: str, slug: str, title: str, description: str, meta: dict) -> None:
    """index.htmlのジャンル一覧・記事一覧に新しいエントリを自動追記する"""
    index_path = SITE_DIR / "index.html"
    if not index_path.exists():
        print("警告: site/index.html が見つからないため、トップページの更新をスキップしました。")
        return

    html = index_path.read_text(encoding="utf-8")

    price_range = meta.get("price_range", "")
    product_count = meta.get("product_count", "")
    read_minutes = meta.get("read_minutes", "")

    article_card = f"""    <article class="featured">
      <div class="thumb">
        <svg viewBox="0 0 80 100" width="90" aria-hidden="true">
          <rect x="20" y="10" width="40" height="80" rx="4" fill="#fff" stroke="var(--accent)" stroke-width="2"/>
          <rect x="30" y="0" width="20" height="14" rx="2" fill="var(--accent)"/>
        </svg>
      </div>
      <div>
        <span class="tag-pr">PR / 比較レビュー</span>
        <h3><a href="articles/{slug}.html">{title}</a></h3>
        <p>{description}</p>
        <div class="meta-row">
          <span>比較商品数：{product_count}点</span>
          <span>価格帯：{price_range}</span>
          <span class="mono">読了目安：約{read_minutes}分</span>
        </div>
      </div>
    </article>
"""
    if f'articles/{slug}.html' not in html:
        html = html.replace("<!-- AUTO_ARTICLES_END -->", article_card + "    <!-- AUTO_ARTICLES_END -->")

    frequency = meta.get("frequency", "")
    genre_card = f"""      <div class="genre-card">
        <span class="status live">公開中</span>
        <h4>{genre_name}</h4>
        <p>買い替え頻度：{frequency}</p>
      </div>
"""
    if f">{genre_name}<" not in html:
        html = html.replace("<!-- AUTO_GENRES_END -->", genre_card + "      <!-- AUTO_GENRES_END -->")

    index_path.write_text(html, encoding="utf-8")


# ---------------------------------------------------------------------------
# タスク3: Pinterest投稿案生成
# ---------------------------------------------------------------------------
def task_pinterest() -> None:
    html_files = sorted(ARTICLES_DIR.glob("*.html"), key=lambda p: p.stat().st_mtime, reverse=True)
    if not html_files:
        print("記事が見つかりません。先に article タスクを実行してください。")
        return

    latest = html_files[0]
    content = latest.read_text(encoding="utf-8")
    title_match = re.search(r"<h1>(.*?)</h1>", content, re.DOTALL)
    title_text = re.sub(r"<[^>]+>", "", title_match.group(1)).strip() if title_match else latest.stem

    prompt = f"""次の記事をもとに、Pinterestの投稿案を10本作ってください。
記事タイトル：{title_text}
記事URL：（公開後に手動で追記してください。想定パス: articles/{latest.name}）
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
