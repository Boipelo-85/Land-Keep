"""Start the existing FastAPI and Vite applications together (Python standard library only)."""
from pathlib import Path
import hashlib
import json
import urllib.parse
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
    print('Preparing database (existing records are retained)...', flush=True)
    run([python, '-m', 'alembic', 'upgrade', 'head'], cwd=BACKEND)
    run([python, 'initialize_demo.py'], cwd=BACKEND)
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
            opener = urllib.request.build_opener(urllib.request.ProxyHandler({}))
            def request(path, body=None, token=None, form=False):
                headers = {}
                if token:
                    headers['Authorization'] = 'Bearer ' + token
                data = None
                if body is not None:
                    headers['Content-Type'] = 'application/x-www-form-urlencoded' if form else 'application/json'
                    data = (urllib.parse.urlencode(body) if form else json.dumps(body)).encode()
                req = urllib.request.Request('http://127.0.0.1:5173/api' + path, data=data, headers=headers)
                with opener.open(req, timeout=30) as response:
                    return json.load(response)
            landlord = request('/auth/login', {'email': 'landlord@landkeep.test', 'password': 'password123'})['token']
            request('/applications', token=landlord)
            assert request('/maintenance/classifier/status', token=landlord)['trained'] is True
            prop = request('/units/properties', {'name': 'Launcher QA', 'address': '1 Test Road', 'city': 'Pretoria'}, landlord)
            unit = request('/units', {'property_id': prop['id'], 'unit_number': 'QA01', 'bedrooms': 1, 'monthly_rent': 4500}, landlord)
            assert any(x['id'] == unit['id'] for x in request('/units/vacant'))
            applicant = request('/auth/register', {'full_name': 'QA Applicant', 'email': f'qa-{time.time_ns()}@example.test', 'password': 'password123'})['token']
            application = request('/applications', {'unit_id': unit['id'], 'monthly_income': 20000, 'id_number': '9001015009087', 'consent_given': True}, applicant)
            assert application['unit']['id'] == unit['id']
            tenant = request('/auth/login', {'email': 'tenant@landkeep.test', 'password': 'password123'})['token']
            lease = next(x for x in request('/leases/mine', token=tenant) if x['status'] == 'active')
            conv = request('/maintenance/conversations', {'lease_id': lease['id']}, tenant)
            cid = conv['id']
            response = request(f'/maintenance/conversations/{cid}/messages', {'text': 'The kitchen tap is leaking'}, tenant, True)
            assert response['messages'][-1]['role'] == 'bot'
            response = request(f'/maintenance/conversations/{cid}/escalate', {}, tenant)
            assert 'While you wait:' in response['messages'][-1]['text']
            assert 'catch drips' in response['messages'][-1]['text']
            assert response['classification']['source'] == 'trained_local_model'
            assert response['classification']['category'] == 'plumbing'
            assert response['classification']['suggested_priority'] in {'low', 'high'}
            rid = response['request_id']
            assert any(x['id'] == rid and x['classification']['category'] == 'plumbing' for x in request('/maintenance/requests', token=landlord))
            contractor = request('/contractors', {'name':'QA Plumber','trade':'plumbing'}, landlord)
            work = request(f'/contractors/requests/{rid}/assign', {'contractor_id':contractor['id'],'notes':'Inspect leak'}, landlord)
            assert work['status']=='assigned'
            payment_data = request('/payments/mine', token=tenant)
            assert all('checkout' in charge for charge in payment_data['charges'])
            response = request(f'/maintenance/conversations/{cid}/messages', {'text': 'I cant find mu unit keys hey.'}, tenant, True)
            assert 'locked out' in response['messages'][-1]['text']
            response = request(f'/maintenance/conversations/{cid}/messages', {'text': 'It is not fixed'}, tenant, True)
            assert response['status'] == 'escalated'
            print('PASS: publish property/unit, tenant vacancy browsing/application, frontend proxy, both logins, classifier, chatbot advice, landlord report visibility, and follow-up.', flush=True)
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
