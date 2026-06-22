# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

"""LangChain support for Agent365 observability.

Provides span enrichment that adapts LangChain telemetry to the Agent365
export pipeline, converting OpenTelemetry gen-ai structured messages to the
content shape expected by Agent365 and mapping conversation identifiers to
session identifiers.
"""
