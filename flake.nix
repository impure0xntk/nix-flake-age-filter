{
  description = "A Nix flake utility library to check the age of flake inputs, inspired by npm's min-release-age. Prevents supply chain attacks by ensuring inputs are not too recent.";

  inputs.nixpkgs.url = "github:NixOS/nixpkgs/nixos-unstable";

  outputs = { self, nixpkgs }:
    let
      inherit (nixpkgs) lib;
      inherit (lib) filterAttrs mapAttrs attrNames concatStringsSep floor;

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

      # CLI packages for nix run - delegate to shell.nix which builds the Python package
      packages = lib.genAttrs nixpkgs.lib.systems.flakeExposed (system:
        let
          pkgs = nixpkgs.legacyPackages.${system};
          inherit (pkgs) lib;
          python = pkgs.python312;
        in
        {
          default = pkgs.callPackage ./nix/default.nix {
            inherit lib python;
            inherit (python.pkgs) rich typer requests click shellingham typing-extensions whenever;
          };
          nix-flake-age = pkgs.callPackage ./nix/default.nix {
            inherit lib python;
            inherit (python.pkgs) rich typer requests click shellingham typing-extensions whenever;
          };
        });

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
