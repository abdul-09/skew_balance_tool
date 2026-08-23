from __future__ import annotations

from pathlib import Path

import pytest

from skewproof.config import ConfigError, load_registry
from skewproof.definition import FeatureRegistry

VALID_CONFIG = '''
from skewproof.definition import Aggregation, FeatureRegistry, feature

registry = FeatureRegistry()

feature(
    registry,
    name="soil_latest",
    source="soil_readings",
    entity_key="farmer_id",
    timestamp_key="event_ts",
    value_key="moisture",
    aggregation=Aggregation.LATEST,
)
'''


def write(tmp_path: Path, name: str, content: str) -> Path:
    path = tmp_path / name
    path.write_text(content)
    return path


class TestLoadRegistry:
    def test_loads_a_valid_config(self, tmp_path: Path) -> None:
        path = write(tmp_path, "features.py", VALID_CONFIG)
        reg = load_registry(path)
        assert isinstance(reg, FeatureRegistry)
        assert reg.get("soil_latest").source == "soil_readings"

    def test_accepts_str_path(self, tmp_path: Path) -> None:
        path = write(tmp_path, "features.py", VALID_CONFIG)
        reg = load_registry(str(path))
        assert reg.get("soil_latest") is not None

    def test_missing_file_raises_config_error(self, tmp_path: Path) -> None:
        with pytest.raises(ConfigError, match="config file not found"):
            load_registry(tmp_path / "does_not_exist.py")

    def test_unrecognized_extension_raises_config_error(self, tmp_path: Path) -> None:
        # An extension importlib doesn't have a loader for (unlike .py) - e.g. someone
        # accidentally points --config at the wrong kind of file.
        path = write(tmp_path, "features.txt", VALID_CONFIG)
        with pytest.raises(ConfigError, match="could not load config file"):
            load_registry(path)

    def test_syntax_error_raises_config_error(self, tmp_path: Path) -> None:
        path = write(tmp_path, "broken.py", "this is not python(((")
        with pytest.raises(ConfigError, match="error executing config file"):
            load_registry(path)

    def test_missing_registry_attribute_raises_config_error(self, tmp_path: Path) -> None:
        path = write(tmp_path, "no_registry.py", "x = 1\n")
        with pytest.raises(ConfigError, match="does not define a module-level 'registry'"):
            load_registry(path)

    def test_wrong_registry_type_raises_config_error(self, tmp_path: Path) -> None:
        path = write(tmp_path, "wrong_type.py", "registry = 'not a registry'\n")
        with pytest.raises(ConfigError, match="is not a FeatureRegistry"):
            load_registry(path)

    def test_invalid_definition_raises_config_error(self, tmp_path: Path) -> None:
        content = VALID_CONFIG + '\nfeature(registry, name="", source="s", ' \
            'entity_key="e", timestamp_key="t", value_key="v")\n'
        path = write(tmp_path, "invalid_def.py", content)
        with pytest.raises(ConfigError, match="error executing config file"):
            load_registry(path)

    def test_duplicate_registration_raises_config_error(self, tmp_path: Path) -> None:
        content = VALID_CONFIG + '\nfeature(registry, name="soil_latest", source="s", ' \
            'entity_key="e", timestamp_key="t", value_key="v")\n'
        path = write(tmp_path, "dup_def.py", content)
        with pytest.raises(ConfigError, match="already registered"):
            load_registry(path)
