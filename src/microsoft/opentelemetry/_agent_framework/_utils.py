# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""Utility functions for Agent Framework observability extensions."""

from __future__ import annotations

# Re-export from shared enricher utilities for backward compatibility.
from microsoft.opentelemetry.a365.core.enricher_utils import (  # noqa: F401  # pylint: disable=unused-import
    extract_content_as_string_list,
    extract_input_content,
    extract_output_content,
)
