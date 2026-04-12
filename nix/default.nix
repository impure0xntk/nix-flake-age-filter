{ lib, pkgs, python3Packages }:

let
  pkg = pkgs.python3Packages.buildPythonPackage rec {
    allowDirty = true;
    format = "setuptools";
    nativeBuildInputs = [ python3Packages.setuptools python3Packages.wheel ];
    pname = "nix-flake-age-filter";
    version = "0.1.0";

    src = ../.;
    sourceRoot = ".";

    propagatedBuildInputs = [ python3Packages.rich python3Packages.typer ];

    checkPhase = ''
      ${pkgs.python3}/bin/python -c "import nix_flake_age_filter.nix_flake_age_update; print('import ok')"
    '';

    meta = with lib; {
      description = "CLI that updates Nix flake inputs only if commits are older than a given minimum age";
      homepage = "https://github.com/impure0xntk/nix-flake-age-filter";
      license = licenses.mit;
      maintainers = with maintainers; [];
      platforms = platforms.unix;
    };
  };
in
{
  nix-flake-age-filter = pkg;
}
