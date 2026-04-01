"""Microsoft OpenTelemetry distro package."""


def enable_genai_langchain():
    try:
        import opentelemetry.instrumentation.langchain
        import langchain_openai
    except ImportError:
        raise ImportError(
            "Missing dependencies for GenAI LangChain support. "
            "Install them with: pip install microsoft-opentelemetry-distro-python[genai-langchain]"
        )
    # ... rest of the setup


def configure_microsoft_opentelemetry() -> None:
    """Placeholder entry point for distro configuration."""
    enable_genai_langchain()

