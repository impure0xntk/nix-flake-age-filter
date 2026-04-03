# nix-flake-age-filter

npm v11.10.0の `min-release-age` と同様の機能を Nix Flake で実現するためのユーティリティライブラリ。

## 概要

`min-release-age` は、公開から指定日数が経過していないパッケージのインストールを防止するサプライチェーン攻撃対策機能です。
このライブラリは、flake inputs の `lastModified` を使用し、同様の年齢チェックを Nix Flake で実現します。

## 使い方

### 他のflakeから利用する

```nix
{
  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    age-filter.url = "github:impure0xntk/nix-flake-age-filter";
  };

  outputs = { self, nixpkgs, age-filter }:
    let
      inherit (age-filter.lib) checkAllInputs mkAgeCheck;
    in
    {
      # 年齢チェックの結果を取得
      yourCheck = age-filter.lib.checkAllInputs {
        inputs = self.inputs;
        minAgeDays = 3;        # 最低3日以上経過していること
        referenceTime = self.lastModified or 0;
        excludeInputs = [ "self" ];
      };

      # flake checkとして登録
      checks.x86_64-linux.input-age = age-filter.lib.mkAgeCheck {
        inputs = self.inputs;
        minAgeDays = 3;
        referenceTime = self.lastModified or 0;
        system = "x86_64-linux";
        excludeInputs = [ "self" "nixpkgs" ];
      };
    };
}
```

### 自前のチェックを定義する

```nix
{
  inputs = {
    age-filter.url = "github:impure0xntk/nix-flake-age-filter";
  };

  outputs = { self, age-filter }:
    {
      checks.x86_64-linux.my-inputs = age-filter.lib.mkAgeCheck {
        inputs = self.inputs;
        minAgeDays = 7;  # 7日未満の入力を禁止
        referenceTime = self.lastModified or 0;
        system = "x86_64-linux";
        excludeInputs = [ "self" ];
      };
    };
}
```

## 比較表: npm vs nix-flake-age-filter

| 機能 | npm (`min-release-age`) | nix-flake-age-filter |
|------|------------------------|---------------------|
| 入力値 | パッケージの公開日 | flake input の `lastModified` |
| 現在時刻 | システム時刻 (impure) | `self.lastModified` / `referenceTime` (pure) |
| 動作タイミング | `npm install` 時 | `nix flake check` 時 |
| 設定方法 | `.npmrc` | flake outputs の checks |
| デフォルト | なし | なし |

## 技術的な背景

### npm `min-release-age` の動作

npm v11.10.0で導入された `min-release-age` は、パッケージツリーを構築する際に、公開から指定日数が経過していないバージョンを除外します。

```ini
# .npmrc
min-release-age=3
```

### Nix で同機能を実現する難しさ

Nix flakes は **pure（純粋）** である必要があるため、`builtins.currentTime` のような変更可能な値に依存できません。
そのため、このライブラリでは **`self.lastModified`** をリファレンス時刻として使用します。

`self.lastModified` は、このflakeが最後に更新された時刻（gitの最終コミット時刻など）であり、同じリビジョンであれば常に同じ値を返すため、pure evaluation と互換性があります。

## API リファレンス

### `lib.checkInputAge`

単一のinputの年齢をチェックします。

```nix
age-filter.lib.checkInputAge {
  input = inputs.foo;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
}
# => { ok = true, ageDays = 15, error = null; }
```

### `lib.checkAllInputs`

全てのinputを一括チェックします。

```nix
age-filter.lib.checkAllInputs {
  inputs = self.inputs;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
  excludeInputs = [ "self" "nixpkgs" ];
}
# => { ok = true, results = { ... }, failed = [], error = null; }
```

### `lib.mkAgeCheck`

flake checkとして使用可能なderivationを作成します。

```nix
age-filter.lib.mkAgeCheck {
  inputs = self.inputs;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
  system = "x86_64-linux";
  excludeInputs = [ "self" "nixpkgs" ];
}
```

### `lib.mkChecks`

`flakeExposed`の全システムに対してチェックを生成します。

```nix
age-filter.lib.mkChecks {
  inputs = self.inputs;
  minAgeDays = 3;
  referenceTime = self.lastModified or 0;
  excludeInputs = [ "self" "nixpkgs" ];
}
```

### `lib.daysToSeconds`

日数を秒数に変換します。

```nix
age-filter.lib.daysToSeconds 3
# => 259200
```

## 制限事項

- `referenceTime` として `self.lastModified` を使用するため、flakeが頻繁に更新される場合は、チェックの厳密さが変わることがあります
- gitではない入力ソース（URLやpathなど）では `lastModified` が利用できない場合があります。その場合はチェックをスキップします

## ライセンス

Apache License 2.0
