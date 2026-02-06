# video-asset-organizer

Windowsで動画/画像/音声素材を、**撮影日（なければ更新日時）**で `YYYY/MM/DD` に自動整理するツールです。

## 1. 要件整理

### 目的
- 素材フォルダ（取り込み先）にたまるファイルを日付別フォルダに整理し、編集前の管理をシンプルにする。

### 対象ファイル（MVP）
- `.mp4` / `.mov` / `.png` / `.jpg` / `.wav`

### 日付判定ルール
1. `exiftool` で撮影日時メタデータを取得（`DateTimeOriginal` / `CreateDate` / `MediaCreateDate`）
2. 取得できない場合はファイルの更新日時 (`mtime`) を使用
3. 出力先は `YYYY/MM/DD` フォルダ

### 実行方針
- 初期値は **dry-run（実ファイル変更なし）**
- `--execute` を指定したときのみコピー/移動を実行
- ログはファイル出力して履歴確認可能

---

## 2. フォルダ構成案（運用）

```txt
D:\Footage\
  Incoming\              # 取り込み先（監視・スキャン対象）
  Sorted\                # 整理後出力
    2026\01\30\
    2026\01\31\
  Backup\                # move時の退避コピー（任意）
  Logs\                  # 実行ログ
```

---

## 3. 命名規則（提案）

### 出力フォルダ
- `YYYY/MM/DD`（例: `2026/01/30`）

### ファイル名衝突時
- 同名ファイルが存在する場合は連番を付与
- 例: `clip.mp4` → `clip_001.mp4` → `clip_002.mp4`

---

## 4. 除外条件（提案）

### 拡張子除外
- `.tmp`, `.part`, `.crdownload`

### ファイル名プレフィックス除外
- `thumb*`, `thumbnail*`, `~$*`, `.*`

### そのほか
- 対象拡張子以外は処理しない

---

## 5. MVPスクリプト

- ファイル: `src/organize_assets.py`
- 機能:
  - 指定フォルダ再帰スキャン
  - 日付判定（メタデータ優先、失敗時は更新日時）
  - `YYYY/MM/DD` へ copy/move
  - dry-run（デフォルト）
  - ログ出力
  - move時のバックアップ（任意）

---

## 6. セットアップ

```bash
python -m venv .venv
.venv\Scripts\activate
```

`exiftool` があると撮影日時を優先利用できます（未インストールでも更新日時で動作）。

---

## 7. 使い方

## 7.1 dry-run（デフォルト）

```bash
python src/organize_assets.py --source "D:\Footage\Incoming" --output "D:\Footage\Sorted"
```

- 実ファイルは変更せず、ログに「どこへ振り分けるか」を出力します。

## 7.2 実行（コピー）

```bash
python src/organize_assets.py --source "D:\Footage\Incoming" --output "D:\Footage\Sorted" --execute --mode copy
```

## 7.3 実行（移動 + バックアップ）

```bash
python src/organize_assets.py --source "D:\Footage\Incoming" --output "D:\Footage\Sorted" --execute --mode move --backup-dir "D:\Footage\Backup"
```

---

## 8. ログ出力

デフォルトログファイル:

```txt
logs/organizer.log
```

変更したい場合:

```bash
python src/organize_assets.py --source "D:\Footage\Incoming" --output "D:\Footage\Sorted" --log-file "D:\Footage\Logs\organizer.log"
```

---

## 9. バックアップ運用

- `--mode move` のとき `--backup-dir` を指定すると、移動前に原本を退避コピーします。
- 誤振り分け時は Backup から復元可能です。
- 初期運用は `--mode copy` または dry-run で検証してから move へ移行を推奨します。
