# -------------------------------------------------------------------------
# Copyright (c) Microsoft Corporation. All rights reserved.
# Licensed under the MIT License. See License.txt in the project root for
# license information.
# --------------------------------------------------------------------------


def remap_disable_to_enable(kwargs, disable_key, enable_key):
    """Convert a disable_* kwarg to enable_* for configure_azure_monitor."""
    if disable_key in kwargs:
        kwargs[enable_key] = not kwargs.pop(disable_key)
