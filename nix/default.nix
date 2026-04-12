{ lib
, python
, rich
, typer
, pygit2
, requests
, click
, shellingham
, typing-extensions
, whenever
}:

python.pkgs.buildPythonPackage rec {
  pname = "nix-flake-age-filter";
  version = "0.1.0";

  format = "pyproject";

  src = lib.cleanSource ../.;

  nativeBuildInputs = [ python.pkgs.hatchling ];

  propagatedBuildInputs = [ rich typer pygit2 requests whenever click shellingham typing-extensions ];

  checkPhase = ''
    ${python.interpreter} -c "from flake_age_filter.cli.main import app; print('import ok')"
  '';

  meta = with lib; {
    description = "CLI that updates Nix flake inputs only if commits are older than a given minimum age";
    homepage = "https://github.com/impure0xntk/nix-flake-age-filter";
    license = licenses.mit;
    maintainers = with maintainers; [];
    platforms = platforms.unix;
  };
}
