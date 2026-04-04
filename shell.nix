{ pkgs ? import <nixpkgs> { } }:

let
  python = pkgs.python3.withPackages (ps: with ps; [
    pytest
    requests
    rich
    pygit2
  ]);

  src = ./src;

  # CLI dispatch script
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
        exec ${python.interpreter} ${src}/nix_flake_age_verify.py "$@"
        ;;
      update)
        exec ${python.interpreter} ${src}/nix_flake_age_update.py "$@"
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

  cliPackage = pkgs.writeShellApplication {
    name = "nix-flake-age";
    runtimeInputs = [ pkgs.git pkgs.nix ];
    text = builtins.readFile cliScript;
  };
in

pkgs.mkShell {
  name = "nix-flake-age-dev";

  packages = [
    cliPackage
    python
  ];

  shellHook = ''
    echo "=== nix-flake-age-filter development environment ==="
    echo ""
    echo "CLI: nix-flake-age verify|update"
    echo "Tests: cd tests && nix flake check"
    echo ""
    export PYTHONPATH="${toString src}:$PYTHONPATH"
  '';
}
