"""Desktop app entry point — launched by Electron.

Sets LOCAL storage backend, picks a free port, runs uvicorn,
and prints READY:<port> to stdout so Electron knows when to load the UI.
"""

import os
import socket
import sys


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else _find_free_port()

    # Force LOCAL mode for desktop
    os.environ.setdefault("STORAGE_BACKEND", "LOCAL")
    os.environ["APP_PORT"] = str(port)

    import uvicorn

    # Print ready signal for Electron *before* blocking on serve
    print(f"READY:{port}", flush=True)

    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=port,
        log_level="info",
    )


if __name__ == "__main__":
    main()
