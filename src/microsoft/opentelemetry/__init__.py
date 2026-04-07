# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# -------------------------------------------------------------------------

from microsoft.opentelemetry._configure import use_microsoft_opentelemetry

from ._version import VERSION

__all__ = [
    "use_microsoft_opentelemetry",
]
__version__ = VERSION
