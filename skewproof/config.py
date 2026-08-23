"""
Load a FeatureRegistry from a user's Python config file.

skewproof intentionally has no bespoke config file format (YAML/JSON/etc). The
README's own example already defines features in plain Python, so the CLI reuses
exactly that: point it at any .py file exposing a module-level `registry`
FeatureRegistry, and it's loaded the same way Python would import it. No new file
format to design or document, no new dependency, and definition validation (every
FeatureDefinition's __post_init__, every registry.register() duplicate check) runs
for free as a side effect of executing the file - there is nothing extra to keep in
sync with what FeatureDefinition already enforces.

The tradeoff, made deliberately: this executes the file. A config file is trusted
input here, the same way a Python test file or the demo script is - this is not
meant for loading configs from an untrusted source.
"""
from __future__ import annotations

import importlib.util
from pathlib import Path

from .definition import FeatureRegistry


class ConfigError(Exception):
    """Raised when a config file can't be loaded or doesn't expose a registry."""


def load_registry(path: str | Path) -> FeatureRegistry:
    path = Path(path)
    if not path.is_file():
        raise ConfigError(f"config file not found: {path}")

    spec = importlib.util.spec_from_file_location(f"skewproof_config_{path.stem}", path)
    if spec is None or spec.loader is None:
        raise ConfigError(f"could not load config file: {path}")

    module = importlib.util.module_from_spec(spec)
    try:
        spec.loader.exec_module(module)
    except Exception as exc:
        raise ConfigError(f"error executing config file {path}: {exc}") from exc

    registry = getattr(module, "registry", None)
    if registry is None:
        raise ConfigError(f"{path} does not define a module-level 'registry'")
    if not isinstance(registry, FeatureRegistry):
        got = type(registry).__name__
        raise ConfigError(f"{path}'s 'registry' is not a FeatureRegistry (got {got})")
    return registry
