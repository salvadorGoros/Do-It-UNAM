"""Inicia el servidor local y lo publica temporalmente con Cloudflare Tunnel."""
import os
import queue
import re
import shutil
import subprocess
import sys
import threading
from pathlib import Path


BASE_DIR = Path(__file__).resolve().parent
TUNNEL_URL = re.compile(r"https://[a-z0-9-]+\.trycloudflare\.com")


def forward_output(name, stream, output):
    for line in iter(stream.readline, ""):
        output.put((name, line.rstrip()))
    stream.close()


def stop_process(process):
    if process is None or process.poll() is not None:
        return
    process.terminate()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    cloudflared = shutil.which("cloudflared")
    if cloudflared is None:
        print(
            "No se encontró cloudflared. Instálalo con "
            "'winget install --id Cloudflare.cloudflared' y vuelve a intentarlo.",
            file=sys.stderr,
        )
        return 1

    environment = os.environ.copy()
    environment["DJANGO_PUBLIC_TUNNEL"] = "1"
    processes = []
    output = queue.Queue()
    threads = []

    try:
        commands = [
            ("Servidor", [
                sys.executable, str(BASE_DIR / "manage.py"),
                "runserver", "127.0.0.1:8000", "--noreload",
            ]),
            ("Cloudflare", [
                cloudflared, "tunnel", "--url", "http://127.0.0.1:8000",
            ]),
        ]
        for name, command in commands:
            process = subprocess.Popen(
                command,
                cwd=BASE_DIR,
                env=environment,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                encoding="utf-8",
                errors="replace",
                bufsize=1,
            )
            processes.append(process)
            thread = threading.Thread(
                target=forward_output,
                args=(name, process.stdout, output),
                daemon=True,
            )
            thread.start()
            threads.append(thread)

        print("Iniciando el servidor local y el túnel. Presiona Ctrl+C para detenerlos.")
        link_announced = False
        while True:
            try:
                name, line = output.get(timeout=0.25)
                print(f"[{name}] {line}", flush=True)
                if name == "Cloudflare" and not link_announced:
                    match = TUNNEL_URL.search(line)
                    if match:
                        print(f"\nComparte este enlace: {match.group(0)}\n", flush=True)
                        link_announced = True
            except queue.Empty:
                pass

            for name, process in zip(("Servidor", "Cloudflare"), processes):
                exit_code = process.poll()
                if exit_code is not None:
                    print(f"{name} terminó inesperadamente (código {exit_code}).", file=sys.stderr)
                    return 1
    except KeyboardInterrupt:
        print("\nDeteniendo el servidor y el túnel...")
        return 0
    finally:
        for process in reversed(processes):
            stop_process(process)
        for thread in threads:
            thread.join(timeout=1)


if __name__ == "__main__":
    raise SystemExit(main())
