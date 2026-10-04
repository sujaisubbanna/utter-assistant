---
title: "はじめかた"
description: "Utter を使い始めて最初の 10 分: 2 つのプッシュトゥトークキー、最初のモデルの選び方、2 つのモードとスリープモード。"
banner:
  content: '未レビューの機械翻訳です。<a href="https://github.com/sujaisubbanna/utter-assistant/blob/main/docs/TRANSLATING.md">翻訳への協力方法</a>。'
---

このページは Utter がインストール済みであることを前提としています。まだの場合は
[インストールの概要](/install/) から始めてください。

## 要件

- **Wayland** 上の Linux。**niri** と **KDE Plasma (KWin)** は第一級のサポートです。他のコンポジタは
  部分的なサポート(ディクテーション、入力、起動。ウィンドウ操作なし)。**macOS もサポートされています。**
- オーディオには **PipeWire**。
- **Python 3.12 以降**。
- 大きなモデルには NVIDIA GPU を推奨しますが、必須ではありません。Utter は
  モデルなしでも、CPU のみの音声認識でも動作します。

## 1. ランナーを起動して設定アプリを開く

```bash
systemctl --user enable --now utter-runner.service   # start the background runner
assistant doctor                                     # check tools, plugins and permissions
utter-gui                                            # open the settings window
```

`utter-gui` が見つからない場合、インストーラーのプレフィックスが `PATH` にない可能性があります:

```bash
export PATH="$HOME/.local/bin:$PATH"
```

`assistant doctor` は、どのコマンドラインツールが不足しているか、ユーザーが入力デバイスを
読み取れるかを教えてくれます。よくある解決策は
[トラブルシューティング](/help/troubleshooting/) にまとめています。

## 2. プッシュトゥトークキーを設定する {#2-set-your-push-to-talk-keys}

Utter にはモードごとに 1 つずつ、**2 つ**のプッシュトゥトークキーがあります。どちらも
evdev のキー名で、設定アプリの **Voice** ページ、または
`~/.config/utter/config.toml` の `[ptt]` で設定します:

```toml
[ptt]
dictation_key = "KEY_F13"
assistant_key = "KEY_INSERT"
```

| | 押し続ける | 言葉はどうなるか | 画面 |
|---|---|---|---|
| **アシスタント** | *アシスタントキー*(既定は Insert) | アクションに変換: アプリやサイトを開く、クリック、ショートカットを押す | 黄色の波形 |
| **ディクテーション** | *ディクテーションキー*(既定は F13) | 開始したフィールドに入力(Linux と macOS の両方で動作) | 「Dictation · typing」付きの青い波形 |

各モードには独自の開始サウンドがあるので、見なくても区別できます。

既定値は、扱いにくい物理キーを Insert や F13 に変換するキーボードリマップを前提としています。
ほとんどの人は、実際にキーボードにあるキーを使いたいでしょう。任意の evdev 名が使えます
(`KEY_RIGHTCTRL`、`KEY_PAUSE`、`KEY_SCROLLLOCK`、...)。`keyd` を使っている場合、
[設定ガイド](/guides/configuration/#keyd-remap) に Caps Lock と右 Alt を
既定値に割り当てる方法があります。

キーリスナーは、ユーザーが `input` グループに属していることだけを必要とします。キーボードを
奪うことはないので、他のアプリでもキーは機能し続けます。

## 3. 最初のモデルを選ぶ

**Models** ページを開きます。**Recommended for your computer** セクションがプロセッサ、
メモリ、グラフィックスカードを調べ、段階ごとに 1 つのモデルを提案します:

| 段階 | すること | 必要な場面 |
|---|---|---|
| **音声認識** | 声をテキストに変換 | 話すすべてのこと |
| **決定モデル** | ルールに一致しないとき、用意されたアクションの中から選ぶ | あいまいな表現(「pull up youtube」) |
| **スクリーンビジョン** | スクリーンショット上で説明された要素を見つける | アクセシビリティが失敗したときの「click the search box」 |

あなたなしでダウンロードされることはありません。まず音声認識から始めてください。それがなければ
アシスタントキーは文字起こしするものがありません。決定モデルとビジョンモデルは任意で、後から追加できます。

提案の横の **Get it** を押すか、`hf:org/name` のようなソースを
**Add a model** に貼り付けます。ダウンロードは中断しても再開され、SHA-256 ダイジェストで検証されます。
[モデルガイド](/guides/models/) に、GPU クラスごとの推奨と
モデルストアの仕組みが書かれています。

## 4. 何か話してみる

アシスタントキーを押しながら **「open youtube」** と言って離します。ブラウザが開くか、既存の YouTube
タブがフォーカスされます。次に試してみましょう:

- 「close this」「fullscreen」「workspace 3」「focus right」(ウィンドウとワークスペースの操作)
- 「pause」「next track」(任意の MPRIS メディアプレーヤー)
- 「new tab」「find」(フォーカス中のアプリ自身のショートカット)
- 「click the search box」(まずアクセシビリティ、インストールしていれば次にビジョン)

ディクテーションキーを押しながら話すと、開始したフィールドに入力されます(Linux と macOS の両方で
動作します)。ディクテーションはコマンドを実行しません。

Utter が *何をするか* を実行せずに確認するには、ソースチェックアウトからドライランを使います:

```bash
python3 -m utter.daemon --text "open youtube" --dry-run
```

## 5. スリープモード {#5-sleep-mode}

アシスタントモードで **「go to sleep」** と言うと、Utter はグラフィックスカードを解放します。
AI モデルサービスが停止し、音声モデルがアンロードされ、小さなリスナーだけが生き残ります。
**どちらかのプッシュトゥトークキーを押し続けると復帰します**: 音声は一瞬で戻り、
大きなモデルはバックグラウンドで再読み込みされます。

Utter は 15 分間使われないと **自動的にも**眠ります。Utter の活動
(プッシュトゥトークキー、話されたコマンド、復帰)だけがカウントされ、他のアプリでの入力やクリックは
決してカウントされないので、作業中はグラフィックスカードが解放されます。復帰も同じキー押下です。

フレーズとタイマーは **General** ページ、または設定ファイルで選べます:

```toml
[sleep]
enabled = true
trigger = ["go to sleep", "take a break"]
services = ["utter-vision", "utter-planner"]   # what gets unloaded
unload_speech = true
on_idle = true                                 # sleep by itself when unused…
idle_minutes = 15                              # …after this long
```

:::note[ローディング状態]
オンスクリーンディスプレイには `loading` 状態があり、復帰やコールドスタート後にモデルが
戻る間、表示されます。
:::

## 次のステップ

- [設定](/guides/configuration/): すべての設定セクション、音声バックエンド、
  決定ヘッド、ビジョン、オーディオ。
- [アプリとアクション](/guides/apps-and-actions/): アプリのショートカットを編集したり、
  Utter に新しいアプリケーションを教えたりする。
- [信頼と安全性](/guides/trust-and-safety/): ターミナルコマンドや生の入力を有効にする前に。
