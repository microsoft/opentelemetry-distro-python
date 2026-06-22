# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from enum import Enum


class InferenceOperationType(Enum):
    """Supported inference operation types for generative AI."""

    #: A chat-completion style request.
    CHAT = "Chat"
    #: A text-completion style request.
    TEXT_COMPLETION = "TextCompletion"
    #: A multimodal content-generation request.
    GENERATE_CONTENT = "GenerateContent"
