# アーキテクチャ設計ドキュメント

## 概要

Nix Flake の `flake.lock` に入っている各 input のコミット日付を検証し、指定日数以上の古いコミットのみを許可するツール。
npm の `min-release-age` に相当する概念を Nix エコシステムに提供する。

2つのサブコマンドを提供する：

| サブコマンド | 説明 |
|-------------|------|
| `verify` | 既存の `flake.lock` の input が最小経過日数を満たしているか検証 |
| `update` | `nix flake update` のラッパーとして、最小経過日数を満たすコミットのみを採用 |

## ディレクトリ構造

```
nix-flake-age-filter/
├── pyproject.toml              # パッケージ定義、依存関係、エントリポイント
├── README.md
├── docs/
│   └── design.md               # 本ファイル
├── src/
│   └── flake_age_filter/
│       ├── __init__.py         # バージョン情報
│       ├── __main__.py         # CLI エントリポイント (click)
│       ├── cli/
│       │   ├── verify.py       # verify サブコマンドの定義
│       │   └── update.py       # update サブコマンドの定義
│       ├── core/
│       │   ├── flake_input.py  # FlakeInput ドメインモデル
│       │   ├── lock_file.py    # flake.lock のパース・バリデーション
│       │   ├── age_check.py    # コミット年齢の判定ロジック
│       │   └── errors.py       # カスタム例外クラス
│       ├── git_ops/
│       │   ├── client.py       # GitClient プロトコル（インターフェース定義）
│       │   ├── github_api.py   # GitHub REST API によるコミット情報取得
│       │   └── libgit2.py      # pygit2 による汎用 git リポジトリ操作
│       └── output/
│           └── formatters.py   # 出力の整形（rich テーブル / JSON）
├── tests/
│   ├── test_flake_input.py
│   ├── test_lock_file.py
│   └── test_age_check.py
└── scripts/
    └── flake-age               # CLI ラッパー（インストール不要な代替経路）
```

## 依存関係

| パッケージ | 用途 |
|-----------|------|
| `click` | CLI フレームワーク（サブコマンド、引数パース） |
| `rich` | コンソール出力の整形（テーブル、色付きテキスト） |
| `pygit2` | git リポジトリ操作（libgit2 バインディング） |
| `PyGithub` | GitHub REST API クライアント（コミット情報取得） |

## コンポーネント設計

### 全体アーキテクチャ

```
                    ┌─────────────┐
                    │   __main__  │
                    ├─────────────┤
                    │ click.group │
                    └──────┬──────┘
              ┌────────────┴────────────┐
              ▼                         ▼
     ┌──────────────┐         ┌──────────────┐
     │ cli/verify.py│         │ cli/update.py│
     └──────┬───────┘         └──────┬───────┘
            │                        │
            ▼                        ▼
     ┌──────────────┐         ┌──────────────┐
     │ core/*.py    │◄────────┤ core/*.py    │
     │ lock_file.py │         │ lock_file.py │
     │ flake_input  │         │ flake_input  │
     │ age_check    │         │ age_check    │
     │ errors       │         │ errors       │
     └──────┬───────┘         └──────┬───────┘
            │                        │
            ▼                        ▼
     ┌──────────────┐         ┌──────────────┐
     │ git_ops/     │         │ git_ops/     │
     ├──────────────┤         ├──────────────┤
     │ github_api   │         │ github_api   │
     │ libgit2      │         │ libgit2      │
     │ client.py    │         │ client.py    │
     └──────────────┘         └──────┬───────┘
                                     │
              ┌──────────────────────┼──────────────┐
              ▼                      ▼              ▼
       ┌─────────────┐    ┌──────────────┐  ┌─────────────┐
       │output/      │    │nix subprocess│  │output/      │
       │formatters.py│    │(update のみ) │  │formatters.py│
       └─────────────┘    └──────────────┘  └─────────────┘
```

### core/ — ドメインロジック

#### `flake_input.py` — FlakeInput ドメインモデル

flake.lock 内の1つの input を表現する。flake.lock の `nodes.<name>` に含まれる `locked` と `original` の情報を保持。

```python
@dataclass(frozen=True)
class FlakeInput:
    name: str
    locked: dict
    original: dict
```

責務：
- git URL の構築 (`to_git_url()`)
- flake URL の構築 (`to_flake_url()`)
- ターゲットブランチの解決 (`target_ref()`)
- nixpkgs 判定 (`is_nixpkgs()`)

URL 構築は GitHub, GitLab, SourceHut, 汎用 git, indirect, path の各タイプに対応。

#### `lock_file.py` — flake.lock パーサー

`flake.lock` の JSON を解析し、直接ルート input だけを抽出する。

```python
def parse_flake_lock(path: Path) -> dict:
    """flake.lock を解析して JSON 構造体を返す。ファイルが存在しない場合は例外。"""

def extract_locked_inputs(lock_data: dict) -> list[FlakeInput]:
    """ルートノードの直接 input だけを FlakeInput のリストとして抽出。"""
```

`nodes.root.inputs` が dict か list かで判定ロジックが変わる点に注意。

#### `age_check.py` — 年齢判定

コミットの Unix タイムスタンプと最小経過日数から、条件を満たすかを判定。

```python
def check_age(timestamp: int, min_age_days: int, now: datetime) -> AgeResult:
    """経過日数を計算し、閾値以上かを判定。"""

def format_duration(days: int) -> str:
    """日数を人間可読な文字列に変換 (例: "3w 2d", "1y 5w")。"""
```

#### `errors.py` — カスタム例外

```python
class FlakeAgeError(Exception): ...
class FlakeLockNotFoundError(FlakeAgeError): ...
class CommitFetchError(FlakeAgeError): ...
class RateLimitError(FlakeAgeError): ...
class AgeValidationError(FlakeAgeError): ...
class NixExecutionError(FlakeAgeError): ...
```

既存の `{"ok": False, "error": ...}` パターンを廃止し、例外で統一する。

### git_ops/ — git 操作層

プロトコルベースのフォールバックチェーン：GitHub API → pygit2

#### `client.py` — GitClient プロトコル

```python
class GitClient(Protocol):
    def commit_timestamp(self, url: str, rev: str, timeout: int) -> int: ...
    def find_commit_at_cutoff(self, url: str, ref: str, cutoff_ts: int, timeout: int) -> CommitSearchResult: ...
```

レートリミット時は指数バックオフ（exponential backoff）でリトライする。

#### `github_api.py` — GitHub REST API (PyGithub)

GitHub ホストの input に対して `PyGithub` ライブラリを使用する。直接 HTTP リクエストを行うよりも型安全で、認証（トークン利用時）やレートリミットのハンドリングが組み込みで提供される。

| 用途 | PyGithub による実装イメージ |
|------|--------------------------|
| 特定 SHA のタイムスタンプ取得 | `repo.get_commit(sha).commit.committer.date` |
| 日付以前で最新のコミット探索 | `repo.get_commits(sha=ref, until=cutoff_date)` |
| レートリミット対応 | `RateLimitExceededException` を捕捉し `RateLimitError` に変換 |

環境変数 `GITHUB_TOKEN` が設定されている場合は自動的に認証され、レートリミットが緩和される（60回/時 → 5000回/時）。

#### `libgit2.py` — pygit2 操作

非 GitHub ホスト（GitLab, SourceHut, 汎用 git）に対して pygit2 で直接 git 操作。

手順：
1. `pygit2.init_repository(path, bare=True)` で一時ベアリポジトリ作成
2. `remote.create()` でリモート追加
3. `remote.fetch(depth=1)` で shallow fetch
4. `commit.commit_time` でタイムスタンプ取得

ターゲットコミット探索時は depth を段階的に拡張しながら walk する。

### cli/ — サブコマンド

#### verify `flake-age verify [OPTIONS] [FLAKE_LOCK]`

既存の `flake.lock` を検証。

オプション：
- `--min-age`（必須）: 最小経過日数
- `--timeout`: 各 input のタイムアウト秒数
- `--skip-ref-check`: ls-remote 参照チェックのスキップ
- `--exclude`: 除外 input 名
- `--json`: JSON 出力
- `--verbose`/`-v`: 詳細表示

実行フロー：
```
flake.lock パース
→ 各 input に対して:
  1. GitClient でコミットタイムスタンプ取得
  2. check_age() で年齢判定
  3. 結果を蓄積
→ formatter で出力
→ 1件でも FAIL/ERROR で exit 1
```

#### update `flake-age update [OPTIONS] [INPUTS...]`

`nix flake update` のラッパーとして、最小経過日数を満たすコミットのみを採用。

オプション：
- `--min-age`（必須）: 最小経過日数
- `--timeout`: 各 input のタイムアウト秒数
- `--exclude`: 除外 input 名（デフォルト: `["self"]`）
- `--dry-run`: nix の実行は行わない
- `--json`: JSON 出力
- `--verbose`/`-v`: 詳細表示
- `--flake-lock`: flake.lock のパス

実行フロー：
```
flake.lock 存在確認
  ├─ 存在しない → flake.nix から inputs を抽出し、直接 flake.lock を生成
  └─ 存在する → 既存 lock をパース

→ 各 input に対して:
  1. GitClient.find_commit_at_cutoff() で条件を満たす最新コミットを探索
  2. 現在の locked_rev で十分な場合はスキップ
  3. 条件を満たすコミットが見つかったら flake URL を構築
  4. nix flake update --override-input で更新
→ 結果を出力
```

`flake.lock` 未存在時のフォールバック：
1. `nix flake lock` で初期 lock 生成を試行
2. 失敗時は flake.nix を regex でパースし、pygit2/GitHub API で直接コミットを解決
3. flake.lock 互換の JSON を直に生成

### output/ — 出力

#### `formatters.py`

rich の `Table` と `Console` を使用した整形出力と、`json.dumps` による JSON 出力を提供。

```python
def print_verify_table(results: list[VerifyResult], min_age: int, json_output: bool) -> None: ...
def print_update_summary(results: list[UpdateResult], json_output: bool, dry_run: bool) -> None: ...
def print_json(results: list[dict]) -> None: ...
```

## CLI インターフェース仕様

### エントリポイント

```
flake-age --help
flake-age verify [OPTIONS] [FLAKE_LOCK]
flake-age update [OPTIONS] [INPUTS...]
```

pyproject.toml で以下のように定義：

```toml
[project.scripts]
flake-age = "flake_age_filter.__main__:main"
```

### `__main__.py`

```python
import click
from flake_age_filter.cli.verify import verify
from flake_age_filter.cli.update import update

@click.group()
@click.version_option()
def main():
    """Nix flake input の最小経過日数を検証・更新する CLI"""
    pass

main.add_command(verify)
main.add_command(update)
```

## データフロー

### verify コマンド

```
flake.lock ──► lock_file.parse_flake_lock() ──► dict
                                            │
                                            ▼
                          extract_locked_inputs() ──► list[FlakeInput]
                                                       │
                                            ┌──────────┴──────────┐
                                            ▼                      ▼
                              github_api.commit_timestamp    libgit2.commit_timestamp
                                            │                      │
                                            └──────────┬───────────┘
                                                       ▼
                                                 check_age()
                                                       │
                                                       ▼
                                              list[VerifyResult]
                                                       │
                                                       ▼
                                                formatters.py
```

### update コマンド

```
flake.lock存在?
  ├─ Yes → parse → list[FlakeInput]
  └─ No  → nix flake lock (or regex parse) → list[FlakeInput]
                                    │
                                    ▼
                find_commit_at_cutoff(GitClient)
                                    │
                            ┌───────┴───────┐
                            ▼               ▼
                       十分なコミット   条件を満たす
                       既存で十分       新コミット発見
                            │               │
                            ▼               ▼
                        結果に記録    override URL 構築 →
                           │          nix flake update
                           ▼               │
                                   list[UpdateResult]
                                            │
                                            ▼
                                       formatters.py
```

## テスト戦略

| レイヤ | テスト対象 | 方法 |
|--------|-----------|------|
| `core/flake_input` | URL 変換、ref 解決 | ユニットテスト（モック不要） |
| `core/lock_file` | flake.lock パース | フィクスチャー JSON を使用 |
| `core/age_check` | 日付計算 | 境界値テスト（ちょうど閾値、1日前後） |
| `git_ops/github_api` | API 呼び出し | `responses` で HTTP モック |
| `git_ops/libgit2` | pygit2 操作 | 一時リポジトリを使用した結合テスト |
| `cli/` | サブコマンド | `click.testing.CliRunner` |

## 将来の拡張ポイント

- 設定ファイル (`.flake-age.toml`) によるデフォルト値の定義
- GitHub トークン認証 (`GITHUB_TOKEN` 環境変数)
- 並列処理（`asyncio` + `aiohttp`）による検証の高速化
- CI 統合（GitHub Actions での自動検証ステップ）
- 出力フォーマットの追加（JUnit XML, SARIF）
