# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------

from typing import Any, Union
from collections.abc import Sequence

ConfigurationValue = Union[
    str,
    bool,
    int,
    float,
    Any,  # Resource, MetricReader, View, etc.
    Sequence[str],
    Sequence[bool],
    Sequence[int],
    Sequence[float],
    Sequence[Any],
]

__all__ = ["ConfigurationValue"]
