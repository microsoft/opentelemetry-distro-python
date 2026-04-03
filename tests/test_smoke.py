from microsoft.opentelemetry import configure_microsoft_opentelemetry


def test_configure_microsoft_opentelemetry_exists() -> None:
    assert callable(configure_microsoft_opentelemetry)
