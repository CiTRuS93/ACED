"""Portable browser-test entry point for CI and contributors."""

import socket
import subprocess
import sys
import time
from urllib.request import urlopen


def main():
    with socket.socket() as reservation:
        reservation.bind(("127.0.0.1", 0))
        port = reservation.getsockname()[1]
    server = subprocess.Popen([sys.executable, "tests/manager/browser_server.py", str(port)])
    try:
        for _ in range(100):
            if server.poll() is not None:
                raise RuntimeError("Browser fixture server exited")
            try:
                with urlopen(f"http://127.0.0.1:{port}/", timeout=1) as response:
                    if response.status == 200:
                        break
            except OSError:
                time.sleep(0.1)
        else:
            raise TimeoutError("Browser fixture server did not become ready")
        subprocess.run([sys.executable, "tests/manager/browser_journey.py", str(port)], check=True)
    finally:
        server.terminate()
        try:
            server.wait(timeout=10)
        except subprocess.TimeoutExpired:
            server.kill()
            server.wait()


if __name__ == "__main__":
    main()
