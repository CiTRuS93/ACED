"""Fixed-token offline server used only by the browser test harness."""

import sys

import uvicorn

from aced.manager.demo import create_demo_app

if __name__ == "__main__":
    port = int(sys.argv[1]) if len(sys.argv) > 1 else 8765
    uvicorn.run(
        create_demo_app(
            origin=f"http://127.0.0.1:{port}",
            bootstrap_token="browser-fixture-token-at-least-32-characters",
        ),
        host="127.0.0.1",
        port=port,
        access_log=False,
    )
