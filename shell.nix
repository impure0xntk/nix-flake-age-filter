{ pkgs ? import <nixpkgs> {} }:

let
  python = pkgs.python3;
  myPackage = pkgs.callPackage ./nix/default.nix {
    inherit python;
    inherit (python.pkgs) rich typer requests click shellingham typing-extensions whenever;
  };
in
pkgs.mkShell {
  # Development tools and runtime dependencies.
  buildInputs = [
    python
    python.pkgs.hatchling
    python.pkgs.pytest
    myPackage
    pkgs.nix
    pkgs.git
  ];

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
