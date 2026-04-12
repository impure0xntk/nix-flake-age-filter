{ lib, python3Packages, python }:

python3Packages.buildPythonPackage rec {
  pname = "nix-flake-age-filter";
  version = "0.1.0";

  # Use the current repository checkout as source.
  src = ./..;

  # Enable PEP‑517 building using the pyproject.toml defined at the repo root.
  pyproject = true;

  # Runtime dependencies.
  propagatedBuildInputs = with python3Packages; [
    rich
  ];

  # Minimal sanity check – import the CLI to ensure the package installs correctly.
  checkPhase = ''
    ${python3Packages.python.interpreter} -c "import nix_flake_age_update; print('import ok')"
  '';

  meta = with lib; {
    description = "CLI that updates Nix flake inputs only if commits are older than a given minimum age";
    homepage    = "https://github.com/impure0xntk/nix-flake-age-filter";
    license     = licenses.mit;
    maintainers = with maintainers; [ ];
    platforms   = platforms.unix;
  };
}
