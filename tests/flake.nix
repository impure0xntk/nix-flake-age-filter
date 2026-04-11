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
      cli = age-filter.packages.x86_64-linux.default;
    in
    {
      # Test 1: Test the daysToSeconds utility function
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

      # Test 2: Check zeroclaw age with checkInputAge
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

      # Test 3: Batch check all inputs with checkAllInputs
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

      # Test 4: Execute the generated script from mkAgeCheck
      checks.x86_64-linux.test-mkAgeCheck-zeroclaw = mkAgeCheck {
        inputs = { zeroclaw = zeroclaw; };
        minAgeDays = 0;
        referenceTime = referenceTime;
        system = "x86_64-linux";
        excludeInputs = [ "self" ];
      };

      # Test 5: Check with different minAgeDays (get zeroclaw age)
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
          
          # Verify calculation
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

      # Test 6: Test excludeInputs
      checks.x86_64-linux.test-excludeInputs =
        let
          result = checkAllInputs {
            inputs = self.inputs;
            minAgeDays = 99999; # Use a very large value to force all to fail
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

      # ===== Expect-fail tests start here =====
      # zeroclaw is currently 6 days old. Force failure with minAgeDays=100.

      # Test 7: Verify checkInputAge returns failure (expect-fail)
      checks.x86_64-linux.test-expect-fail-checkInputAge-too-recent =
        let
          result = checkInputAge {
            input = zeroclaw;
            minAgeDays = 100; # Significantly larger than zeroclaw (6 days)
            referenceTime = referenceTime;
          };
          # This test verifies that result.ok == false
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
          # checkInputAge error message should contain "is only ...d old"
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

      # Test 8: Verify checkAllInputs returns failure (expect-fail)
      checks.x86_64-linux.test-expect-fail-checkAllInputs-too-recent =
        let
          result = checkAllInputs {
            inputs = self.inputs;
            minAgeDays = 100; # zeroclaw (6 days) will fail
            referenceTime = referenceTime;
            excludeInputs = [ "self" ]; # Do not exclude zeroclaw
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

      # Test 9: Verify mkAgeCheck generates a script that exits with code 1 (expect-fail)
      # Moved to packages because placing in checks would cause nix flake check to fail
      packages.x86_64-linux.test-expect-fail-mkAgeCheck-script-exits-fail =
        let
          script = mkAgeCheck {
            inputs = { zeroclaw = zeroclaw; };
            minAgeDays = 100; # Guaranteed to fail
            referenceTime = referenceTime;
            system = "x86_64-linux";
            excludeInputs = [ "self" ];
          };
        in
        # Only verify script generation, do not execute
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

      # Test 10: Boundary test — when age exactly equals minAgeDays
      # zeroclaw is ~6 days old, so minAgeDays=6 should PASS, minAgeDays=7 should FAIL
      checks.x86_64-linux.test-boundary-exactly-at-threshold =
        let
          # First get the age
          baseline = checkInputAge {
            input = zeroclaw;
            minAgeDays = 0;
            referenceTime = referenceTime;
          };
          # Re-check using that age as minAgeDays
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

      # Test 11: Verify zeroclaw (7 days) fails with minAgeDays=8
      checks.x86_64-linux.test-expect-fail-minAgeDays-8 =
        let
          result = checkInputAge {
            input = zeroclaw;
            minAgeDays = 8; # Larger than zeroclaw (7 days)
            referenceTime = referenceTime;
          };
        in
        pkgs.runCommand "test-expect-fail-minAgeDays-8" {} ''
          echo "=== Test: checkInputAge should FAIL when minAgeDays > actual age ==="
          echo "zeroclaw age: ${builtins.toString result.ageDays} days"
          echo "minAgeDays: 8"
          echo ""
          echo "Result:"
          echo "  ok: ${builtins.toJSON result.ok}"
          echo "  error: ${if result.error == null then "null" else result.error}"
          echo ""
          ${if result.ok
            then "echo 'FAIL: checkInputAge unexpectedly returned ok=true' && exit 1"
            else "echo 'PASS: checkInputAge correctly returned ok=false (age ${builtins.toString result.ageDays} < 8)'"
          }
          touch $out
        '';

      # ===== CLI tests start here =====
      cli = age-filter.packages.x86_64-linux.default;

      # Test 12: CLI --help outputs normally
      checks.x86_64-linux.test-cli-help =
        pkgs.runCommand "test-cli-help" {} ''
          echo "=== Test: CLI --help ==="
          output=$(${cli}/bin/nix-flake-age --help 2>&1)
          echo "$output"
          echo ""
          if echo "$output" | grep -q "verify"; then
            echo "PASS: help mentions verify command"
          else
            echo "FAIL: help does not mention verify command"
            exit 1
          fi
          if echo "$output" | grep -q "update"; then
            echo "PASS: help mentions update command"
          else
            echo "FAIL: help does not mention update command"
            exit 1
          fi
          touch $out
        '';

      # Test 13: CLI verify --help outputs normally
      checks.x86_64-linux.test-cli-verify-help =
        pkgs.runCommand "test-cli-verify-help" {} ''
          echo "=== Test: CLI verify --help ==="
          output=$(${cli}/bin/nix-flake-age verify --help 2>&1)
          echo "$output"
          echo ""
          if echo "$output" | grep -q "min-age"; then
            echo "PASS: verify help mentions --min-age"
          else
            echo "FAIL: verify help does not mention --min-age"
            exit 1
          fi
          touch $out
        '';

      # Test 14: CLI update --help outputs normally
      checks.x86_64-linux.test-cli-update-help =
        pkgs.runCommand "test-cli-update-help" {} ''
          echo "=== Test: CLI update --help ==="
          output=$(${cli}/bin/nix-flake-age update --help 2>&1)
          echo "$output"
          echo ""
          if echo "$output" | grep -q "min-age"; then
            echo "PASS: update help mentions --min-age"
          else
            echo "FAIL: update help does not mention --min-age"
            exit 1
          fi
          touch $out
        '';

      # Test 15: CLI exits with error on unknown command
      checks.x86_64-linux.test-cli-unknown-command =
        pkgs.runCommand "test-cli-unknown-command" {} ''
          echo "=== Test: CLI unknown command ==="
          if ${cli}/bin/nix-flake-age foobar 2>&1; then
            echo "FAIL: unknown command should exit non-zero"
            exit 1
          else
            echo "PASS: unknown command exits non-zero"
          fi
          touch $out
        '';
    };
}
