"""
Small command-line entry point for running poolctl manually.

The systemd service normally starts the web server/runtime loop on the Pi. This
module keeps a simple Python entry point available for development, debugging,
or future command-line operation.
"""

from __future__ import annotations

from poolctl.web.server import main


if __name__ == "__main__":
    main()
