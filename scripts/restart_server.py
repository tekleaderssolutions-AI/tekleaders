"""Kill process on port 8000 and start uvicorn (run from project root)."""
import os
import subprocess
import sys
import time

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
PORT = 8000


def kill_port(port: int) -> None:
    out = subprocess.run(
        ["netstat", "-ano"],
        capture_output=True,
        text=True,
        check=False,
    )
    pids = set()
    for line in out.stdout.splitlines():
        if f":{port}" in line and "LISTENING" in line:
            parts = line.split()
            if parts:
                pids.add(parts[-1])
    for pid in pids:
        if pid.isdigit() and int(pid) != os.getpid():
            subprocess.run(
                ["taskkill", "/F", "/PID", pid],
                capture_output=True,
                check=False,
            )
            print(f"Stopped PID {pid} on port {port}")


def main() -> None:
    os.chdir(ROOT)
    kill_port(PORT)
    time.sleep(1)
    python = os.path.join(ROOT, "venv", "Scripts", "python.exe")
    if not os.path.isfile(python):
        python = sys.executable
    subprocess.Popen(
        [python, "-m", "uvicorn", "main:app", "--host", "127.0.0.1", "--port", str(PORT), "--reload"],
        cwd=ROOT,
    )
    print(f"Started server at http://127.0.0.1:{PORT}")


if __name__ == "__main__":
    main()
