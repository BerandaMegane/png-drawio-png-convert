# PNG 注釈ツール

元の PNG を背景として draw.io で赤丸などの注釈を追加し、元画像と同じピクセルサイズの PNG に書き出すためのツールです。注釈は draw.io の図データとして PNG 内に残るため、後から再編集できます。

## 必要なもの

- Windows 10 / 11
- Python 3.10 以上。uv が必要な Python を管理・導入するため、システムへの Python の個別インストールは必須ではありません。
- [uv](https://docs.astral.sh/uv/)
- [draw.io Desktop](https://github.com/jgraph/drawio-desktop/releases/latest)（CLI を含む Windows インストーラーまたは ZIP 版）

## インストール

### uv と Python

PowerShell で uv をインストールします。WinGet が使えない場合は、 [uv の公式インストール手順](https://docs.astral.sh/uv/getting-started/installation/) を参照してください。

```powershell
winget install --id astral-sh.uv -e
```

PowerShell を開き直して、uv と Python を用意します。以下では Python 3.14 を例にしていますが、このツールの対応範囲は Python 3.10 以上です。

```powershell
uv --version
uv python install 3.14
```

このツールは uv のスクリプト依存関係機能を使います。Pillow は `annotate.py` の先頭にある依存関係メタデータに定義されており、初回実行時に uv が自動で用意します。`pip install` や仮想環境の作成は不要です。

### draw.io Desktop

[draw.io Desktop の Releases](https://github.com/jgraph/drawio-desktop/releases/latest) から Windows インストーラーをダウンロードして実行するか、Windows ZIP 版を展開します。

Windows インストーラーを既定の場所にインストールした場合は、次の実行ファイルが使われます。

```text
C:\Program Files\draw.io\draw.io.exe
```

ZIP 版を展開した場合や別の場所にインストールした場合は、実行ファイルのパスを設定してからコマンドを実行します。

```powershell
$env:DRAWIO_EXE = 'D:\Apps\draw.io\draw.io.exe'
```

この設定は現在の PowerShell セッションにのみ適用されます。

## 使い方

PowerShell で `annotate.py` と元画像のあるフォルダーに移動して実行します。

### 1. 編集用 PNG を作る

```powershell
uv run annotate.py init image.png
```

`image.drawio.png` が作られます。入力 PNG の画素データはそのままで、draw.io の図データが PNG 内に追加されます。既定の出力ファイルが既にある場合は上書きしません。

### 2. draw.io で注釈を編集する

`image.drawio.png` を VSCode や draw.io Desktop で開き、赤丸や矢印などを追加して保存します。背景画像はロックされているため、注釈を描くときに背景を誤って動かしにくくなっています。

### 3. 元と同じサイズで書き出す

編集元を残すには、別名で書き出します。

```powershell
uv run annotate.py export image.drawio.png -o image-annotated.png
```

注釈が画像の外にはみ出していても、出力は背景画像と同じ幅・高さになります。書き出した PNG にも draw.io の図データを保持するため、後からそのファイルを draw.io Desktop で開いて再編集できます。

`-o` を省略すると入力ファイルを上書きします。

```powershell
uv run annotate.py export image.drawio.png
```

### 4. サイズと編集データを確認する

```powershell
uv run annotate.py check image-annotated.png --ref image.png
```

参照画像とピクセルサイズが一致すること、および draw.io の図データが含まれることを確認します。`--ref` を省略した場合は、埋め込まれた背景画像とサイズを比較します。

## コマンドとオプション

### `init <image>`

PNG から draw.io で編集できる PNG を作ります。

| オプション | 説明 |
| --- | --- |
| `-o`, `--output <path>` | 出力先。既定は入力ファイル名の拡張子を `.drawio.png` にしたもの（例: `image.drawio.png`）。 |
| `--force` | 既存の出力ファイルを上書きします。 |

例:

```powershell
uv run annotate.py init image.png -o editable.png --force
```

### `export <drawio_png>`

PNG 内の背景画像と注釈を合成して書き出します。元の幅・高さを維持し、編集用の図データも残します。

| オプション | 説明 |
| --- | --- |
| `-o`, `--output <path>` | 出力先。省略すると入力ファイルを上書きします。 |

### `check <drawio_png>`

PNG の寸法と、draw.io 図データの有無を確認します。

| オプション | 説明 |
| --- | --- |
| `--ref <image>` | 寸法比較に使う元画像。省略時は PNG 内の背景画像を使います。 |

## ヘルプ

```powershell
uv run annotate.py --help
uv run annotate.py init --help
uv run annotate.py export --help
uv run annotate.py check --help
```

## ライセンス

このプロジェクトは [MIT License](LICENSE) で公開しています。
