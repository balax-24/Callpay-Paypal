"""Start CallPay's API and Next.js app behind Replit's single public web port."""

from __future__ import annotations

import os
import signal
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

ROOT = Path(__file__).resolve().parent
API_DIR = ROOT / "services" / "api"
WEB_DIR = ROOT / "apps" / "web"


def _start_web(web_port: int, env: dict[str, str]) -> subprocess.Popen:
    args = ["npm", "run", "start", "--", "--hostname", "127.0.0.1", "--port", str(web_port)]
    if os.name == "nt":
        return subprocess.Popen(["cmd", "/c", *args], cwd=WEB_DIR, env=env, creationflags=subprocess.CREATE_NEW_PROCESS_GROUP)
    return subprocess.Popen(args, cwd=WEB_DIR, env=env, start_new_session=True)


def _start_gateway(env: dict[str, str]) -> subprocess.Popen:
    kwargs = {"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}
    return subprocess.Popen(["node", str(ROOT / "replit_gateway.mjs")], cwd=ROOT, env=env, **kwargs)


def _stop_process_tree(process: subprocess.Popen) -> None:
    if process.poll() is not None:
        return
    if os.name == "nt":
        subprocess.run(
            ["taskkill", "/PID", str(process.pid), "/T", "/F"],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
    else:
        try:
            os.killpg(process.pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _request_shutdown(_signum: int, _frame: object) -> None:
    raise KeyboardInterrupt


def _wait_for_api(api: subprocess.Popen, port: int, timeout: int = 120) -> None:
    url = f"http://127.0.0.1:{port}/health"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if api.poll() is not None:
            raise RuntimeError(f"CallPay API exited during startup (exit {api.returncode}).")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    raise TimeoutError("CallPay API did not become healthy within 120 seconds.")


def _wait_for_web(web: subprocess.Popen, port: int, timeout: int = 120) -> None:
    url = f"http://127.0.0.1:{port}/"
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        if web.poll() is not None:
            raise RuntimeError(f"CallPay web exited during startup (exit {web.returncode}).")
        try:
            with urllib.request.urlopen(url, timeout=2) as response:
                if response.status == 200:
                    return
        except (OSError, urllib.error.URLError):
            time.sleep(1)
    raise TimeoutError("CallPay web did not become healthy within 120 seconds.")


def main() -> int:
    signal.signal(signal.SIGTERM, _request_shutdown)
    api_port = int(os.environ.get("CALLPAY_API_PORT", "8000"))
    # Replit maps port 3000; Render and similar hosts pass the public port as PORT.
    web_port = int(os.environ.get("CALLPAY_WEB_PORT") or os.environ.get("PORT") or "3000")
    next_port = int(os.environ.get("CALLPAY_NEXT_PORT", "3001"))
    env = os.environ.copy()
    env.update({
        "CALLPAY_API_PORT": str(api_port),
        "CALLPAY_NEXT_PORT": str(next_port),
        "CALLPAY_WEB_PORT": str(web_port),
        "API_INTERNAL_URL": f"http://127.0.0.1:{api_port}",
    })
    env.setdefault("NEXT_PUBLIC_API_URL", "/api")
    if not env.get("APP_URL") and env.get("RENDER_EXTERNAL_URL"):
        env["APP_URL"] = env["RENDER_EXTERNAL_URL"].rstrip("/") + "/api"  # Render tells us our public URL
    # A single VM has no Kafka broker or local model: turn those off unless the owner configured them,
    # so the app goes straight to its built-in fallbacks instead of waiting on hosts that do not exist.
    for name, value in {
        "KAFKA_BOOTSTRAP": "", "OLLAMA_URL": "", "OLLAMA_DOCKER_URL": "", "REDIS_URL": "",
        "PROVIDERS_LLM": "claude,openai,gemini", "LOCAL_STORAGE_DIR": "/tmp/callpay-storage",
    }.items():
        env.setdefault(name, value)

    missing = [name for name in ("DATABASE_URL", "PAYPAL_CLIENT_ID", "PAYPAL_CLIENT_SECRET") if not env.get(name)]
    if missing:
        print("CallPay is missing deployment secrets/configuration: " + ", ".join(missing), flush=True)

    api = subprocess.Popen(
        [sys.executable, "-m", "uvicorn", "app.main:app", "--host", "127.0.0.1", "--port", str(api_port)],
        cwd=API_DIR,
        env=env,
        **({"creationflags": subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == "nt" else {"start_new_session": True}),
    )
    web: subprocess.Popen | None = None
    gateway: subprocess.Popen | None = None
    try:
        _wait_for_api(api, api_port)
        web = _start_web(next_port, env)
        _wait_for_web(web, next_port)
        gateway = _start_gateway(env)
        print(f"CallPay gateway is listening on 0.0.0.0:{web_port}; Next.js and API stay private on loopback.", flush=True)
        while api.poll() is None and web.poll() is None and gateway.poll() is None:
            time.sleep(1)
        exited = next((process for process in (api, web, gateway) if process is not None and process.poll() is not None), None)
        if exited is None:
            return 0
        return exited.returncode or 0
    except KeyboardInterrupt:
        return 0
    finally:
        for process in (gateway, web, api):
            if process is not None:
                _stop_process_tree(process)
        for process in (gateway, web, api):
            if process is not None:
                try:
                    process.wait(timeout=10)
                except subprocess.TimeoutExpired:
                    process.kill()


if __name__ == "__main__":
    raise SystemExit(main())
