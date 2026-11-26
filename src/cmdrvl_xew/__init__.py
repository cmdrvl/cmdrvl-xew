__all__ = ["__version__", "ARELLE_REQUIREMENT", "REQUIRES_PYTHON"]

__version__ = "0.1.0"

# What packs state in reproduction_steps.json. They repeat pyproject.toml (requires-python and the
# arelle extra); tests/test_arelle_behaviour.py fails if the two disagree. Constants, not installed
# package metadata, so that a pack's bytes do not depend on how the package was installed.
REQUIRES_PYTHON = ">=3.11"
ARELLE_REQUIREMENT = "arelle-release==2.47.5"
