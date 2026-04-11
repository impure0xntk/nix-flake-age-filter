{
  description = "A Nix flake utility library to check the age of flake inputs, inspired by npm's min-release-age. Prevents supply chain attacks by ensuring inputs are not too recent.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;
      inherit (lib) filterAttrs mapAttrs mapAttrs' attrNames concatStringsSep floor;

      # Convert days to seconds
      daysToSeconds = days: days * 24 * 60 * 60;

      # Check if a single input meets the minimum age requirement.
      # Uses `referenceTime` as the "now" — typically `self.lastModified`.
      # Returns { ok :: Bool, ageDays :: Int, error :: String? }
      checkInputAge = { input, minAgeDays, referenceTime }:
        let
          lastMod = input.lastModified or 0;
          ageSeconds = referenceTime - lastMod;
          ageDays = floor (ageSeconds / (24 * 60 * 60));
          ok = ageDays >= minAgeDays;
        in
        {
          inherit ok ageDays;
          error = if ok then null
                  else "input is only ${toString ageDays}d old (minimum: ${toString minAgeDays}d)";
        };

      # Check all inputs against the minimum age requirement.
      # Uses self.lastModified as the reference time for pure evaluation.
      # Returns { ok :: Bool, results :: AttrSet, failed :: [String], error :: String? }
      checkAllInputs = { inputs, minAgeDays, referenceTime, excludeInputs ? [ ] }:
        let
          results = mapAttrs (name: input:
            if lib.elem name excludeInputs then
              { ok = true; ageDays = null; skipped = true; }
            else if !(input ? lastModified) then
              { ok = true; ageDays = null; noTimestamp = true; }
            else
              checkInputAge { inherit input minAgeDays referenceTime; }
          ) inputs;

          failedInputs = attrNames (filterAttrs (_: r: !r.ok) results);
        in
        {
          inherit results;
          ok = failedInputs == [ ];
          failed = failedInputs;
          error = if failedInputs == [ ] then null
                  else "inputs too recent: ${concatStringsSep ", " failedInputs}";
        };

      # Build a flake check derivation that reports input ages.
      # The check runs at evaluation time (pure), embedding results in the script.
      mkAgeCheck = { inputs, minAgeDays, referenceTime, system, excludeInputs ? [ ] }:
        let
          checkResult = checkAllInputs { inherit inputs minAgeDays referenceTime excludeInputs; };
          relevantInputs = filterAttrs (name: input:
            !lib.elem name excludeInputs && input ? lastModified
          ) inputs;
          reportLines = lib.mapAttrsToList (name: input:
            let
              lastMod = input.lastModified;
              cr = checkInputAge { inherit input minAgeDays referenceTime; };
              status = if cr.ok then "OK" else "FAIL";
            in
            "echo '  [${status}] ${name}: age=${toString cr.ageDays}d (lastModified=${toString lastMod})'"
          ) relevantInputs;
          summaryMsg = if checkResult.ok
            then "All inputs pass the ${toString minAgeDays}-day minimum age check."
            else "FAILED: ${checkResult.error}";
          exitCode = if checkResult.ok then 0 else 1;
        in
        nixpkgs.legacyPackages.${system}.writeShellScript "check-input-age" ''
          #!/usr/bin/env bash
          set -euo pipefail

          echo "=== min-release-age check (minimum: ${toString minAgeDays} days) ==="
          echo "Reference time: ${toString referenceTime} ($(date -d @${toString referenceTime} '+%Y-%m-%d %H:%M UTC' 2>/dev/null || echo 'N/A'))"
          echo ""

          ${concatStringsSep "\n" reportLines}
          echo ""
          echo "${summaryMsg}"

          exit ${toString exitCode}
        '';

      # Convenience: create checks for all supported systems
      mkChecks = { inputs, minAgeDays, referenceTime ? self.lastModified or 0, excludeInputs ? [ "self" ] }:
        lib.genAttrs nixpkgs.lib.systems.flakeExposed (system: {
          input-age = mkAgeCheck {
            inherit inputs minAgeDays referenceTime system excludeInputs;
          };
        });

      # Build a CLI package that wraps verify and update scripts
      mkCliPackage = system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          python = pkgs.python3.withPackages (ps: with ps; [
            pygit2
            requests
            rich
            typer
            whenever
          ]);

          # Copy Python scripts into a derivation
          src = pkgs.stdenv.mkDerivation {
            name = "nix-flake-age-cli-src";
            phases = [ "installPhase" ];
            installPhase = ''
              mkdir -p $out/libexec
              cp ${./src/age_check.py} $out/libexec/age_check.py
              cp ${./src/flake_age_common.py} $out/libexec/flake_age_common.py
              cp ${./src/flake_age_types.py} $out/libexec/flake_age_types.py
              cp ${./src/flake_lock.py} $out/libexec/flake_lock.py
              cp ${./src/git_operations.py} $out/libexec/git_operations.py
              cp ${./src/nix_flake_age_verify.py} $out/libexec/nix_flake_age_verify.py
              cp ${./src/nix_flake_age_update.py} $out/libexec/nix_flake_age_update.py
            '';
          };

          # Main entry point: dispatch to subcommands
          cliScript = pkgs.writeShellScript "nix-flake-age" ''
            #!/usr/bin/env bash
            set -euo pipefail

            USAGE="Usage: nix-flake-age <command> [options]

            Commands:
              verify    Verify flake input ages against a minimum threshold
              update    Update flake inputs but only adopt commits >= min-age

            Use 'nix-flake-age <command> --help' for more information."

            command="''${1:-}"
            shift || true

            case "$command" in
              verify)
                exec ${python.interpreter} ${src}/libexec/nix_flake_age_verify.py "$@"
                ;;
              update)
                exec ${python.interpreter} ${src}/libexec/nix_flake_age_update.py "$@"
                ;;
              -h|--help|help)
                echo "$USAGE"
                exit 0
                ;;
              "")
                echo "Error: no command specified" >&2
                echo "$USAGE" >&2
                exit 1
                ;;
              *)
                echo "Error: unknown command '$command'" >&2
                echo "$USAGE" >&2
                exit 1
                ;;
            esac
          '';
        in
        pkgs.writeShellApplication {
          name = "nix-flake-age";
          runtimeInputs = [ pkgs.git pkgs.nix ];
          text = builtins.readFile cliScript;
          meta.mainProgram = "nix-flake-age";
        };

    in
    {
      # Public API: library functions for other flakes to use
      #
      # Usage in your own flake:
      #   age-filter = "${nix-flake-age-filter}";
      #   imports = [ "${age-filter}/lib.nix" ];
      #
      # Or call directly:
      #   age-filter.lib.checkAllInputs { ... }
      lib = {
        inherit checkInputAge checkAllInputs mkAgeCheck mkChecks daysToSeconds;
      };

      # CLI packages for nix run
      packages = lib.genAttrs nixpkgs.lib.systems.flakeExposed (system: {
        default = mkCliPackage system;
        nix-flake-age = mkCliPackage system;
      });

      # Also provide legacyPackages for convenience
      legacyPackages = lib.mapAttrs (_: system: {
        nix-flake-age = mkCliPackage system;
      }) nixpkgs.legacyPackages;

      # Self-check: verify this flake's own inputs
      checks = let
        minAgeDays = 3;
        referenceTime = self.lastModified or 0;
      in
        mkChecks {
          inputs = self.inputs;
          inherit minAgeDays referenceTime;
          excludeInputs = [ "self" "nixpkgs" ];
        };

      # Also expose verify via nix checks for CLI package
      apps = lib.genAttrs nixpkgs.lib.systems.flakeExposed (system: {
        default = {
          type = "app";
          program = "${self.packages.${system}.default}/bin/nix-flake-age";
        };
      });

      # Development shell — delegates to shell.nix
      devShells = lib.genAttrs nixpkgs.lib.systems.flakeExposed (system: {
        default = nixpkgs.legacyPackages.${system}.callPackage ./shell.nix { };
      });
    };
}
