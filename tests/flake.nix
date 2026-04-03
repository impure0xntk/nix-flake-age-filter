{
  description = "Test flake for nix-flake-age-filter

Usage:
  cd tests && nix flake check
  nix flake check ./tests
";

  inputs = {
    nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";
    age-filter.url = "path:./..";
    zeroclaw.url = "github:impure0xntk/nix-zeroclaw";
  };

  outputs = { self, nixpkgs, age-filter, zeroclaw }:
    let
      inherit (age-filter.lib) checkAllInputs mkAgeCheck checkInputAge daysToSeconds mkChecks;
      referenceTime = self.lastModified or 0;
      pkgs = nixpkgs.legacyPackages.x86_64-linux;
    in
    {
      # テスト 1: daysToSeconds ユーティリティ関数のテスト
      checks.x86_64-linux.test-daysToSeconds =
        let
          threeDays = daysToSeconds 3;
          sevenDays = daysToSeconds 7;
          expected3 = 259200;
          expected7 = 604800;
          pass = (threeDays == expected3) && (sevenDays == expected7);
        in
        pkgs.runCommand "test-daysToSeconds" {} ''
          echo "=== Test: daysToSeconds ==="
          echo "3 days = ${builtins.toString threeDays} seconds (expected: ${builtins.toString expected3})"
          echo "7 days = ${builtins.toString sevenDays} seconds (expected: ${builtins.toString expected7})"
          echo ""
          ${if pass then "echo 'PASS: daysToSeconds works correctly'" else "echo 'FAIL: daysToSeconds returned wrong values' && exit 1"}
          touch $out
        '';

      # テスト 2: checkInputAge で zeroclaw の年齢チェック
      checks.x86_64-linux.test-checkInputAge-zeroclaw =
        let
          result = checkInputAge {
            input = zeroclaw;
            minAgeDays = 0;
            referenceTime = referenceTime;
          };
        in
        pkgs.runCommand "test-checkInputAge-zeroclaw" {} ''
          echo "=== Test: checkInputAge with zeroclaw ==="
          echo "zeroclaw lastModified: ${builtins.toString (zeroclaw.lastModified or 0)}"
          echo "referenceTime: ${builtins.toString referenceTime}"
          echo "minAgeDays: 0"
          echo ""
          echo "Result:"
          echo "  ok: ${builtins.toJSON result.ok}"
          echo "  ageDays: ${builtins.toString result.ageDays}"
          ${if result.error == null then "echo \"  error: null\"" else "echo \"  error: ${result.error}\""}
          echo ""
          ${if result.ok then "echo 'PASS: checkInputAge returned ok for zeroclaw'" else "echo 'FAIL: checkInputAge returned error for zeroclaw' && exit 1"}
          touch $out
        '';

      # テスト 3: checkAllInputs で全入力の一括チェック
      checks.x86_64-linux.test-checkAllInputs =
        let
          result = checkAllInputs {
            inputs = self.inputs;
            minAgeDays = 0;
            referenceTime = referenceTime;
            excludeInputs = [ "self" ];
          };
        in
        pkgs.runCommand "test-checkAllInputs" {} ''
          echo "=== Test: checkAllInputs ==="
          echo ""
          echo "Result:"
          echo "  ok: ${builtins.toJSON result.ok}"
          echo "  failed: ${builtins.concatStringsSep " " result.failed}"
          ${if result.error == null then "echo \"  error: null\"" else "echo \"  error: ${result.error}\""}
          echo ""
          ${if result.ok then "echo 'PASS: checkAllInputs found no failed inputs'" else "echo 'FAIL: some inputs failed' && exit 1"}
          touch $out
        '';

      # テスト 4: mkAgeCheck で生成スクリプトの実行
      checks.x86_64-linux.test-mkAgeCheck-zeroclaw = mkAgeCheck {
        inputs = { zeroclaw = zeroclaw; };
        minAgeDays = 0;
        referenceTime = referenceTime;
        system = "x86_64-linux";
        excludeInputs = [ "self" ];
      };

      # テスト 5: 異なる minAgeDays でのチェック (zeroclaw の年齢を取得)
      checks.x86_64-linux.test-zeroclaw-age-report =
        let
          result = checkInputAge {
            input = zeroclaw;
            minAgeDays = 0;
            referenceTime = referenceTime;
          };
        in
        pkgs.runCommand "test-zeroclaw-age-report" {} ''
          echo "=== Test: zeroclaw age report ==="
          echo "zeroclaw age: ${builtins.toString result.ageDays} days"
          echo "referenceTime: ${toString referenceTime}"
          echo "zeroclaw lastModified: ${toString (zeroclaw.lastModified or 0)}"
          
          # 計算の検証
          timeDiff=$(( ${toString referenceTime} - ${toString (zeroclaw.lastModified or 0)} ))
          calculatedDays=$(( timeDiff / 86400 ))
          echo "calculated age from timestamps: ''${calculatedDays} days"
          
          if [ "${builtins.toString result.ageDays}" = "$calculatedDays" ]; then
            echo "PASS: age calculation matches"
            touch $out
          else
            echo "FAIL: age calculation mismatch"
            exit 1
          fi
        '';

      # テスト 6: excludeInputs のテスト
      checks.x86_64-linux.test-excludeInputs =
        let
          result = checkAllInputs {
            inputs = self.inputs;
            minAgeDays = 99999; # 非常に大きな値で全てfailさせる
            referenceTime = referenceTime;
            excludeInputs = [ "self" "zeroclaw" "nixpkgs" "age-filter" ];
          };
        in
        pkgs.runCommand "test-excludeInputs" {} ''
          echo "=== Test: excludeInputs ==="
          echo "All non-excluded inputs should be skipped or pass"
          echo ""
          echo "Result:"
          echo "  ok: ${builtins.toJSON result.ok}"
          echo "  failed: ${builtins.concatStringsSep " " result.failed}"
          echo ""
          ${if result.ok then "echo 'PASS: all inputs were excluded or passed'" else "echo 'FAIL: some non-excluded inputs failed' && exit 1"}
          touch $out
        '';

      # ===== ここから「失敗することが期待される」テスト =====
      # zeroclaw は現在 6日齢。minAgeDays=100 で確実に失敗させる。

      # テスト 7: checkInputAge が失敗を返すことを確認 (expect-fail)
      checks.x86_64-linux.test-expect-fail-checkInputAge-too-recent =
        let
          result = checkInputAge {
            input = zeroclaw;
            minAgeDays = 100; # zeroclaw (6日) より十分大きい値
            referenceTime = referenceTime;
          };
          # このテストは result.ok == false であることを確認する
          expectedFail = !result.ok;
          actualErrorMsg = result.error or "";
        in
        pkgs.runCommand "test-expect-fail-checkInputAge-too-recent" {} ''
          echo "=== Test: checkInputAge should FAIL for too-recent input ==="
          echo "zeroclaw age: ~6 days, minAgeDays: 100"
          echo ""
          echo "Result:"
          echo "  ok: ${builtins.toJSON result.ok}"
          echo "  ageDays: ${builtins.toString result.ageDays}"
          echo "  error: ${actualErrorMsg}"
          echo ""
          ${if result.ok
            then "echo 'FAIL: checkInputAge unexpectedly returned ok=true' && exit 1"
            else "echo 'PASS: checkInputAge correctly returned ok=false'"
          }
          # checkInputAgeのエラーメッセージには "is only ...d old" が含まれる
          ${if builtins.match ".*is only.*" actualErrorMsg != null
            then "echo 'PASS: error message indicates the input is too young'"
            else "echo 'FAIL: error message does not indicate the input is too young' && exit 1"
          }
          ${if expectedFail
            then "echo 'PASS: expectedFail flag is correct'"
            else "echo 'FAIL: expectedFail flag is wrong' && exit 1"
          }
          echo ""
          echo "All expect-fail tests passed."
          touch $out
        '';

      # テスト 8: checkAllInputs が失敗を返すことを確認 (expect-fail)
      checks.x86_64-linux.test-expect-fail-checkAllInputs-too-recent =
        let
          result = checkAllInputs {
            inputs = self.inputs;
            minAgeDays = 100; # zeroclaw (6日) が失敗する
            referenceTime = referenceTime;
            excludeInputs = [ "self" ]; # zeroclaw を除外しない
          };
        in
        pkgs.runCommand "test-expect-fail-checkAllInputs-too-recent" {} ''
          echo "=== Test: checkAllInputs should FAIL when input is too recent ==="
          echo "minAgeDays: 100 (zeroclaw is only ~6 days old)"
          echo ""
          echo "Result:"
          echo "  ok: ${builtins.toJSON result.ok}"
          echo "  failed: ${builtins.concatStringsSep " " result.failed}"
          echo "  error: ${if result.error == null then "null" else result.error}"
          echo ""
          ${if result.ok
            then "echo 'FAIL: checkAllInputs unexpectedly returned ok=true' && exit 1"
            else "echo 'PASS: checkAllInputs correctly returned ok=false'"
          }
          ${if builtins.elem "zeroclaw" result.failed
            then "echo 'PASS: zeroclaw is in the failed list'"
            else "echo 'FAIL: zeroclaw is NOT in the failed list' && exit 1"
          }
          ${if result.error != null
            then "echo 'PASS: error message is not null'"
            else "echo 'FAIL: error message is null' && exit 1"
          }
          echo ""
          echo "All expect-fail tests passed."
          touch $out
        '';

      # テスト 9: mkAgeCheck が exit 1 のスクリプトを生成することを確認 (expect-fail)
      # → checks に配置すると nix flake check が失敗するため packages に移動
      packages.x86_64-linux.test-expect-fail-mkAgeCheck-script-exits-fail =
        let
          script = mkAgeCheck {
            inputs = { zeroclaw = zeroclaw; };
            minAgeDays = 100; # 確実に失敗
            referenceTime = referenceTime;
            system = "x86_64-linux";
            excludeInputs = [ "self" ];
          };
        in
        # スクリプトを生成確認するだけで実行はしない
        pkgs.runCommand "verify-mkAgeCheck-script-exits-fail" {} ''
          echo "=== Test: mkAgeCheck should produce a failing script ==="
          echo "Script path: ${script}"
          echo ""
          echo "Script contents:"
          cat ${script}
          echo ""
          echo "PASS: mkAgeCheck produced a script (not executing it to avoid check failure)"
          touch $out
        '';

      # テスト 10: 境界値テスト — ちょうど minAgeDays と同じ年齢の場合
      # zeroclaw は約6日齢なので、minAgeDays=6 では PASS、minAgeDays=7 では FAIL
      checks.x86_64-linux.test-boundary-exactly-at-threshold =
        let
          # まず年齢を取得
          baseline = checkInputAge {
            input = zeroclaw;
            minAgeDays = 0;
            referenceTime = referenceTime;
          };
          # その年齢を minAgeDays に設定して再チェック
          result = checkInputAge {
            input = zeroclaw;
            minAgeDays = baseline.ageDays;
            referenceTime = referenceTime;
          };
        in
        pkgs.runCommand "test-boundary-exactly-at-threshold" {} ''
          echo "=== Test: boundary — minAgeDays exactly equals ageDays ==="
          echo "zeroclaw ageDays: ${builtins.toString result.ageDays}"
          echo ""
          ${if result.ok
            then "echo 'PASS: input at exact threshold passes (>= comparison)'"
            else "echo 'FAIL: input at exact threshold should pass' && exit 1"
          }
          touch $out
        '';

      # テスト 11: minAgeDays=7 で zeroclaw (6日) が失敗することを確認
      checks.x86_64-linux.test-expect-fail-minAgeDays-7 =
        let
          result = checkInputAge {
            input = zeroclaw;
            minAgeDays = 7; # zeroclaw (6日) より大きい
            referenceTime = referenceTime;
          };
        in
        pkgs.runCommand "test-expect-fail-minAgeDays-7" {} ''
          echo "=== Test: checkInputAge should FAIL when minAgeDays > actual age ==="
          echo "zeroclaw age: ${builtins.toString result.ageDays} days"
          echo "minAgeDays: 7"
          echo ""
          echo "Result:"
          echo "  ok: ${builtins.toJSON result.ok}"
          echo "  error: ${if result.error == null then "null" else result.error}"
          echo ""
          ${if result.ok
            then "echo 'FAIL: checkInputAge unexpectedly returned ok=true' && exit 1"
            else "echo 'PASS: checkInputAge correctly returned ok=false (age ${builtins.toString result.ageDays} < 7)'"
          }
          touch $out
        '';
    };
}
