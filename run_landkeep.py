"""Start the existing FastAPI and Vite applications together (Python standard library only)."""
from pathlib import Path
import hashlib
import os
import shutil
import signal
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parent
BACKEND = ROOT / 'backend'
FRONTEND = ROOT / 'client-vite-scaffold'
RUNTIME = ROOT / '.landkeep-runtime'
LOGS = ROOT / 'logs'
WINDOWS = os.name == 'nt'


def run(args, cwd=ROOT, env=None):
    subprocess.run([str(a) for a in args], cwd=cwd, env=env, check=True)


def available(port):
    with socket.socket() as sock:
        try:
            sock.bind(('127.0.0.1', port))
        except OSError:
            raise RuntimeError(f'Port {port} is already in use. Stop your older LandKeep server and run START-LANDKEEP.cmd again.')


def ready(url):
    try:
        # Local requests should not use machine-wide HTTP proxies.
        with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(url, timeout=1) as response:
            return response.status == 200
    except Exception:
        return False


def stop(process):
    if process.poll() is not None:
        return
    if WINDOWS:
        subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    else:
        os.killpg(process.pid, signal.SIGTERM)
    try:
        process.wait(timeout=8)
    except subprocess.TimeoutExpired:
        process.kill()
        process.wait()


def main():
    if sys.version_info < (3, 10):
        raise RuntimeError('Install Python 3.12 or newer, then try again.')
    npm = shutil.which('npm.cmd' if WINDOWS else 'npm')
    if not npm:
        raise RuntimeError('Install Node.js 24 LTS, reopen the terminal, then try again.')
    for port in (8000, 5173):
        available(port)
    python = RUNTIME / ('Scripts/python.exe' if WINDOWS else 'bin/python')
    if not python.exists():
        print('Creating a clean Python environment (leaves your existing .venv untouched)...', flush=True)
        run([sys.executable, '-m', 'venv', RUNTIME])
    print('Checking backend dependencies. Let installation finish...', flush=True)
    run([python, '-m', 'pip', 'install', '-r', BACKEND / 'requirements.txt'])
    # Catch incomplete installations before attempting to launch the API.
    run([python, '-c', 'import click, uvicorn, fastapi, sqlalchemy; assert hasattr(click, "Choice"), "Click installation is incomplete"'])
    check_model = [python, '-c', "from app.services.maintenance_classifier import load_model; raise SystemExit(0 if load_model() else 1)"]
    if subprocess.run([str(a) for a in check_model], cwd=BACKEND).returncode != 0:
        print('Training maintenance classifier from the bundled labelled dataset...', flush=True)
        run([python, 'train_maintenance_classifier.py'], cwd=BACKEND)
    # Train the local text complaint router if the bundled artifact is missing/incompatible.
    check_complaints = [python, '-c', "from app.services.tenant_complaints import MODEL, _load; _load(MODEL.stat().st_mtime_ns)"]
    if subprocess.run([str(a) for a in check_complaints], cwd=BACKEND).returncode != 0:
        print('Training local tenant complaint model...', flush=True)
        run([python, 'train_tenant_complaints.py'], cwd=BACKEND)
    run([python, 'ensure_secret.py'], cwd=BACKEND)
    print('Preparing database (existing records are retained)...', flush=True)
    run([python, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND)
    lock_hash = hashlib.sha256((FRONTEND / 'package-lock.json').read_bytes()).hexdigest()
    marker = RUNTIME / 'frontend-lock.txt'
    if not (FRONTEND / 'node_modules').exists() or not marker.exists() or marker.read_text() != lock_hash:
        print('Installing frontend dependencies...', flush=True)
        run([npm, 'ci', '--no-audit', '--no-fund'], cwd=FRONTEND)
        marker.write_text(lock_hash)
    LOGS.mkdir(exist_ok=True)
    env = {**os.environ, 'LANDKEEP_API_TARGET': 'http://127.0.0.1:8000'}
    processes = []
    streams = []
    try:
        for name, args, cwd in [
            ('backend', [python, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], BACKEND),
            ('frontend', [npm, 'run', 'dev', '--', '--host', '127.0.0.1', '--port', '5173', '--strictPort'], FRONTEND),
        ]:
            stream = (LOGS / f'{name}.log').open('w', encoding='utf-8')
            streams.append(stream)
            options = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if WINDOWS else {'start_new_session': True}
            processes.append(subprocess.Popen([str(a) for a in args], cwd=cwd, env=env, stdout=stream, stderr=stream, **options))
        print('Starting backend and frontend...', flush=True)
        deadline = time.monotonic() + 60
        while not ready('http://127.0.0.1:5173/api/health'):
            if any(p.poll() is not None for p in processes):
                raise RuntimeError('A server stopped during startup. See the logs below.')
            if time.monotonic() > deadline:
                raise RuntimeError('Backend connection check timed out. See the logs below.')
            time.sleep(.25)
        print('\nLandKeep is running: http://127.0.0.1:5173\nAPI docs: http://127.0.0.1:8000/docs\nKeep this window open. Press Ctrl+C to stop both servers.\n', flush=True)
        if '--smoke-test' in sys.argv:
            print('PASS: frontend proxy and backend health check.', flush=True)
            return
        webbrowser.open('http://127.0.0.1:5173')
        while all(p.poll() is None for p in processes):
            time.sleep(1)
        raise RuntimeError('A server stopped. See the logs below.')
    finally:
        for process in reversed(processes):
            stop(process)
        for stream in streams:
            stream.close()


if __name__ == '__main__':
    try:
        main()
    except KeyboardInterrupt:
        print('\nBoth servers stopped.')
    except Exception as exc:
        print(f'\nSTARTUP FAILED: {exc}', file=sys.stderr)
        for name in ('backend', 'frontend'):
            path = LOGS / f'{name}.log'
            if path.exists():
                print(f'\n{name} log (last 25 lines):\n' + '\n'.join(path.read_text(errors='replace').splitlines()[-25:]), file=sys.stderr)
        sys.exit(1)
