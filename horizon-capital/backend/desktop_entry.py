"""Desktop app entry point — launched by Electron.

Runs the whole system in one process: SQLite/KV storage, the agent org chart and
its workers, the HTTP API, and the built React UI. Prints ``READY:<port>`` on
stdout once the server is actually accepting connections — Electron waits for
that line before loading the window, so an early print means a blank window.

The terminal agent (``python -m app``) is unaffected; this is a second front end
onto the same system.
"""

import asyncio
import os
import socket
import sys


def _find_free_port() -> int:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


async def _serve(port: int) -> None:
    import uvicorn

    config = uvicorn.Config(
        "app.main:app",
        host="127.0.0.1",  # never expose the unauthenticated LOCAL API to the network
        port=port,
        log_level="info",
        access_log=False,
    )
    server = uvicorn.Server(config)
    serve_task = asyncio.create_task(server.serve())

    # Announce only once uvicorn reports the socket is up (or the task died).
    while not server.started and not serve_task.done():
        await asyncio.sleep(0.05)
    if serve_task.done():
        await serve_task  # re-raise the startup failure
        return
    print(f"READY:{port}", flush=True)

    await serve_task


def main() -> None:
    port = int(sys.argv[1]) if len(sys.argv) > 1 else _find_free_port()

    os.environ.setdefault("STORAGE_BACKEND", "LOCAL")
    os.environ.setdefault("HORIZON_RUN_AGENTS", "1")
    os.environ["APP_PORT"] = str(port)

    try:
        asyncio.run(_serve(port))
    except KeyboardInterrupt:
        pass
    except Exception as exc:  # surface the reason in Electron's backend log
        print(f"FATAL:{exc}", flush=True)
        raise


if __name__ == "__main__":
    main()
