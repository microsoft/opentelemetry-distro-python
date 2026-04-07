from microsoft.opentelemetry import use_microsoft_opentelemetry


def test_use_microsoft_opentelemetry_exists() -> None:
    assert callable(use_microsoft_opentelemetry)
