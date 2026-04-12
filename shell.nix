{ pkgs ? import <nixpkgs> {} }:

let
  # Build the python package on‑the‑fly and expose its console script.
  myPackage = pkgs.python3Packages.callPackage ./nix/default.nix {};
in
pkgs.mkShell {
  # Development tools and runtime dependencies.
  buildInputs = with pkgs; [
    python3               # interpreter
    python3Packages.hatchling
    python3Packages.pytest
    nix
    git
  ];

  # Add the built package's bin directory to PATH so `nix-flake-age` is available.
  shellHook = ''
    export PATH=$PATH:${myPackage}/bin
    echo "Development shell for nix-flake-age-filter"
    echo "  python : $(python3 --version)"
    echo "  nix    : $(nix --version)"
    echo "  CLI    : nix-flake-age --help"
  '';
}
