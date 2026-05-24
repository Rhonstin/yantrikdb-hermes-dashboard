"""YantrikDB Hermes Dashboard plugin entrypoint.

The dashboard runs as a local FastAPI app; Hermes plugin discovery only needs a
valid register hook so the plugin can be listed without loader warnings.
"""

from __future__ import annotations


def register(ctx) -> None:
    """Register dashboard plugin metadata with Hermes.

    This dashboard does not expose agent tools or slash commands. Keeping this
    hook intentionally no-op prevents directory-plugin discovery from treating
    the dashboard as malformed.
    """

    return None
