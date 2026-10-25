# The Sun Shining on the World Wiki — Fandom → GitHub Pages 移植版

**対象：** https://ssw-mod.fandom.com/ja/wiki/The_Sun_Shining_on_the_World_Wiki  
**データ：** 管理者から提供された `jasswmod_pages_full.xml.7z` の最新リビジョンを使用。  
**状態：** 記事本文・カテゴリ・情報欄の一次移植まで完了。画像本体は別途取得が必要。

## 移行結果（今回のXML）

| 項目 | 数 |
|---|---:|
| XML内の全ページ（非記事を含む） | 736 |
| 通常名前空間の記事（リダイレクトを除く） | 174 |
| XML内のリダイレクト | 20（うち移行先を解決できたものは6） |
| 国家テンプレートから変換した情報欄 | 133 |
| 人物の情報欄 | 4 |
| 艦艇の情報欄 | 9 |
| その他の情報欄（戦闘・汎用・陣営） | 3 |
| 記事中に登場する、まだローカルにない画像 | 311 |
| リンク先がXML内の通常記事に見当たらないページ | 39 |
| 完全には展開できなかった記事用テンプレート | 1ページ（メインページ/テーマ） |

詳細は `migration/report.json` に記録済みです。記事URLは `migration/url-map.csv`、不足画像は `migration/image-manifest.csv` で検索できます。

## 特徴

- 日本語のMarkdown記事とWiki風の左右サイドバー
- 国家・人物・艦艇・陣営・戦闘・汎用の情報欄（Fandomのテンプレートの項目値を抽出）
- カテゴリ別記事一覧とタグ（HugoのTaxonomy）
- 原Wikiの内部リンク → Hugo内部リンク、XMLに存在しないリンク → 旧Fandomへのリンク
- 元Wikiの編集履歴への参照リンクを各記事に表示
- 軽量なクライアントサイド検索（`search-index.json`）
- GitHub ActionsでGitHub Pagesへ自動配信
- 元Wikitextを `migration/raw/` に保存（対象：記事、テンプレート、カテゴリ、ファイル説明）

## 1. GitHubで公開

1. GitHubで公開リポジトリ `ssw-wiki` を作成する。
2. このフォルダのファイル一式をリポジトリのルートにアップロードする。**ZIPファイル自体をGitHubへ置くのではなく、展開したファイルを配置する。**
3. `hugo.toml` の `USERNAME` をGitHubのユーザー名に変更する。
4. `Settings → Pages → Build and deployment → Source` で **GitHub Actions** を選ぶ。
5. `main` ブランチにpushすると、`.github/workflows/hugo.yml` がHugo v0.168.0でサイトをビルド・公開する。

```bash
git init
git add .
git commit -m "Import SSW Wiki from Fandom XML"
git branch -M main
git remote add origin https://github.com/USERNAME/ssw-wiki.git
git push -u origin main
```

公開URL（例）： `https://USERNAME.github.io/ssw-wiki/`

### ローカル表示

[Hugo](https://gohugo.io/installation/) v0.146以降を導入してから：

```bash
hugo server -D
# http://localhost:1313/
```

**重要：** 今回の実行環境にHugoコマンドがなかったため、記事のXML→Markdown変換は完了していますが、実際のHugo生成・公開テストは未実施です。GitHub Actionsで初回ビルドを確認してください。

## 2. 画像を復元する

FandomのXMLには画像そのものが**含まれません**。国旗・国章・人物画像を表示したければ、
ライセンスや権利を確認した画像を `static/images/` に保存してください。

- 例：`static/images/FLAG_JAP.svg`、`static/images/EMBLEM_JAP.svg`
- 不足ファイル一覧：`migration/report.json` の `images_missing_from_static_images`
- ローカル画像の有無をHugoがビルド時に判定し、追加した画像が情報欄に表示されるようにしています。
- 画像のファイル名はXML中のファイル名（スペースはアンダースコア）に合わせてください。

画像URLを探す補助スクリプトも付属しています。**ネットワークアクセスと画像利用権限を確認のうえ、ローカルのPCで実行してください。** Fandom側のAPI制限等により取得できない場合があります。

```bash
# 最初は数件のリンクを調べるだけ（ダウンロードしない）
python3 scripts/fetch_fandom_images.py --limit 5

# 権利を確認した場合だけ取得（最大10件の例）
python3 scripts/fetch_fandom_images.py --limit 10 --download
```

取得状況は `migration/image-fetch-log.json` に保存されます。
FandomでCC BY-SA表記があっても、**画像がそのライセンスとは限りません**。国旗・MOD素材・写真は個別に確認し、必要に応じて撮影者・作者等を記載してください。

## 3. 記事を編集する

各記事は `content/wiki/article-*.md` です。記事冒頭のFront Matterでカテゴリを変更できます。

```yaml
---
title: "サンプル共和国"
categories: ["国家", "ヨーロッパ"]
infobox:
  template: "国家"
  kind: "country"
  images:
    - label: "国旗"
      filename: "FLAG_SAMPLE.svg"
  fields:
    - label: "首都"
      value: "サンプル市"
    - label: "政府思想"
      value: "民主主義"
---
```

`layouts/page.html`が全記事で共通の情報欄を描画します。国家・人物・艦艇等の情報欄を変更した場合、該当する全記事に反映されます。

新しい記事用の雛形は `archetypes/countries.md` にあります。

## 4. XMLからもう一度取り込む

追加記事などを含む新しいXMLダンプを取得した際は、PandocとPython 3.9以降で再変換できます。

```bash
python3 scripts/import_fandom.py /path/to/jasswmod_pages_full.xml --force
# 自前の画像素材フォルダも指定可能:
python3 scripts/import_fandom.py /path/to/jasswmod_pages_full.xml --assets /path/to/images --force
```

`--force` は生成済みの記事を上書きします。手動編集したファイルを残す場合は、先にGitでcommitしてバックアップしてください。

## 5. 移植できないもの・移植後の確認

1. **画像本体**：XMLにないので追加が必要。
2. **Fandomの独自拡張**：原Wiki固有のギャラリー、Lua、動的テンプレート、複雑な表などは一部手修正が必要。`migration/report.json` の `unconverted_templates` にあるページを優先する。
3. **旧Wikiの編集履歴**：各記事の元Fandomページへリンクしていますが、古い編集をGitのcommit履歴へ変換していません。オリジナルの `.7z` ファイルを手元で保管してください。
4. **一部のリンク切れ**：ダンプにないページへのリンクをFandomに向けています。39件の候補は `missing_internal_link_targets` を確認してください。未解決リダイレクトは14件で、大半はFandom内部のユーザーページ向けです。
5. **著作権・帰属表示**：管理者権限は全画像・全投稿の権利を意味しません。原Wikiのライセンス、投稿者の帰属表示、各画像の利用条件を確認し、GitHub版に必要な表示を追加してください。
6. **旧URLのリダイレクト**：FandomドメインからGitHub Pagesへの301転送はこのZIPだけでは設定できません。移行後は元Wikiのメインページなどから案内してください。

`migration/raw/`には通常記事、テンプレート、カテゴリ、ファイル説明の最新Wikitextを保存しています。ユーザーページなどの名前空間は公開用パッケージに含めていません。

## 主なファイル

| ファイル | 用途 |
|---|---|
| `hugo.toml` | Hugoサイト設定 |
| `content/_index.md` | メインページ |
| `content/wiki/*.md` | 移行後の記事 |
| `layouts/page.html` | 記事テンプレート／情報欄 |
| `layouts/_shortcodes/media.html` | 画像があれば表示、なければ元Wikiへのリンク |
| `static/css/wiki.css` | Wiki全体の外観 |
| `static/search-index.json` | 検索用インデックス |
| `migration/report.json` | 移植結果と未対応事項 |
| `migration/url-map.csv` | 元URL→新URL対応表 |
| `migration/image-manifest.csv` | 不足画像の一覧と確認欄 |
| `migration/raw/` | 元Wikitext（履歴のうち最新版） |
| `.github/workflows/hugo.yml` | GitHub Pagesへの自動公開 |

## 参考資料

- Hugo: https://gohugo.io/
- GitHub Pages: https://docs.github.com/en/pages
- Fandom Wiki: https://ssw-mod.fandom.com/ja/wiki/The_Sun_Shining_on_the_World_Wiki
- MediaWiki API: https://www.mediawiki.org/wiki/API:Imageinfo
