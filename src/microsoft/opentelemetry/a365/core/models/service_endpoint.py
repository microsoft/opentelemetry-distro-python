# Copyright (c) Microsoft Corporation.
# Licensed under the MIT License.

from dataclasses import dataclass
from urllib.parse import urlsplit


@dataclass
class ServiceEndpoint:
    """Represents a service endpoint with hostname, optional port and full URL."""

    hostname: str
    """The hostname of the service endpoint."""

    port: int | None = None
    """The port of the service endpoint."""

    url: str | None = None
    """Optional full endpoint URL. Only supply URLs safe to record in telemetry."""

    @classmethod
    def from_url(cls, url: str) -> "ServiceEndpoint":
        """Create an endpoint from an absolute URL, retaining its path and query.

        Raises:
            ValueError: If the URL lacks a scheme or hostname, or has an invalid port.
        """
        parsed = urlsplit(url)
        if not parsed.scheme or not parsed.hostname:
            raise ValueError("Service endpoint URL must be absolute and include a hostname.")
        port = parsed.port
        if port is None:
            port = {"http": 80, "https": 443}.get(parsed.scheme.lower())
        return cls(hostname=parsed.hostname, port=port, url=url)
