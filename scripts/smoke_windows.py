"""Verifica o executável em modo servidor, sem controlar ou abrir um navegador."""
import http.cookiejar
import json
import os
import secrets
import socket
import subprocess
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path


def main():
    root = Path(__file__).resolve().parents[1]
    executable = root / "dist" / "OrcaFlow.exe"
    with socket.socket() as probe:
        probe.bind(("127.0.0.1", 0))
        port = probe.getsockname()[1]
    with tempfile.TemporaryDirectory(prefix="OrcaFlow-binary-test-") as temporary:
        process = subprocess.Popen([str(executable), "--server", "--data-dir", temporary, "--port", str(port)],
                                   stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                                   creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0)
        base = f"http://127.0.0.1:{port}"
        try:
            for _ in range(100):
                try:
                    with urllib.request.urlopen(base + "/health", timeout=1) as response:
                        health = json.load(response)
                    break
                except (OSError, ValueError):
                    time.sleep(0.2)
            else:
                raise RuntimeError("O executável não iniciou o servidor no tempo esperado.")
            assert health["app"] == "orcaflow" and health["version"] == "2.0.0"
            for path in ("/", "/static/app.js", "/static/style.css", "/static/fonts/public-sans-400.ttf"):
                with urllib.request.urlopen(base + path, timeout=3) as response:
                    assert response.status == 200
                    assert response.read()
            browser = urllib.request.build_opener(urllib.request.HTTPCookieProcessor(http.cookiejar.CookieJar()))
            with browser.open(base + "/api/session") as response:
                csrf = json.load(response)["csrf"]
            data = json.dumps({"name": "Teste isolado", "password": secrets.token_urlsafe(20)}).encode()
            request = urllib.request.Request(base + "/api/setup", data=data,
                                             headers={"Content-Type": "application/json", "X-CSRF-Token": csrf})
            with browser.open(request, timeout=10) as response:
                assert json.load(response)["ok"]
            with browser.open(base + "/api/data", timeout=3) as response:
                assert json.load(response)["customers"] == []
            print("Executável: servidor HTTP, assets locais, autenticação e API verificados em base temporária.")
        finally:
            if os.name == "nt":
                subprocess.run(["taskkill", "/PID", str(process.pid), "/T", "/F"], capture_output=True)
            else:
                process.terminate()
            process.wait(timeout=15)


if __name__ == "__main__":
    main()
