from __future__ import annotations

from collections.abc import MutableMapping

CANONICAL_EXPORTER_ENV_VAR = "ENABLE_A365_OBSERVABILITY_EXPORTER"
LEGACY_EXPORTER_ENV_VAR = "ENABLE_KAIRO_EXPORTER"


def align_exporter_env_flags(environment: MutableMapping[str, str]) -> None:
    canonical_value = environment.get(CANONICAL_EXPORTER_ENV_VAR)
    if canonical_value is None:
        canonical_value = environment.get(LEGACY_EXPORTER_ENV_VAR, "true")

    environment[CANONICAL_EXPORTER_ENV_VAR] = canonical_value
    environment[LEGACY_EXPORTER_ENV_VAR] = canonical_value
