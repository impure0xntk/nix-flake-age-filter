{ pkgs ? import <nixpkgs> {} }:

let
  python = pkgs.python3;
  # Build the python package on‑the‑fly and expose its console script.
  myPackage = pkgs.callPackage ./nix/default.nix {
    inherit python;
    inherit (python.pkgs) rich typer pygit2 requests click shellingham typing-extensions whenever;
  };
in
pkgs.mkShell {
  # Development tools and runtime dependencies.
  buildInputs = [
    python               # interpreter
    python.pkgs.hatchling
    python.pkgs.pytest
    myPackage            # include built package with dependencies (including whenever)
    pkgs.nix
    pkgs.git
  ];

  # Add the built package's bin directory to PATH so `nix-flake-age` is available.
  # Also add the package's Python modules to PYTHONPATH for tests.
  shellHook = ''
    export PYTHONDONTWRITEBYTECODE=1
    export PYTHONPATH=$PWD/src:${myPackage}/${python.sitePackages}:$PYTHONPATH
    export PATH=$PATH:${myPackage}/bin
    echo "Development shell for nix-flake-age-filter"
    echo "  python : $(python3 --version)"
    echo "  nix    : $(nix --version)"
    echo "  CLI    : nix-flake-age --help"
  '';
}
