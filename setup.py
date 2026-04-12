from setuptools import setup, find_packages

setup(
    name="nix-flake-age-filter",
    version="0.1.0",
    packages=find_packages('src'),
    package_dir={"": "src"},
    include_package_data=True,
    install_requires=[
        "rich",
        "typer>=0.12.0",
    ],
    entry_points={
        "console_scripts": [
            "nix-flake-age=nix_flake_age_filter.nix_flake_age_verify:app",
        ],
    },
    python_requires=">=3.9",
)
