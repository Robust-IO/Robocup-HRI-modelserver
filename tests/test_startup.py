import os
from pathlib import Path
import subprocess
import tempfile
import time
import unittest

ENTRYPOINT = Path(__file__).resolve().parents[1] / 'scripts' / 'entrypoint.sh'
MOCK = '''#!/usr/bin/env python3
import http.server, os, sys, time
port = int(sys.argv[sys.argv.index('--port') + 1])
with open(os.environ['START_LOG'], 'a') as f:
    f.write(str(port) + '\\n')
if os.environ.get('FAIL_PORT') == str(port):
    sys.exit(1)
time.sleep(0.3)
class Handler(http.server.BaseHTTPRequestHandler):
    def do_GET(self):
        with open(os.environ['START_LOG'], 'a') as f:
            f.write('ready ' + str(port) + '\\n')
        self.send_response(200)
        self.end_headers()
    def log_message(self, *args):
        pass
http.server.HTTPServer(('127.0.0.1', port), Handler).serve_forever()
'''

class StartupTest(unittest.TestCase):
    def test_order_and_failure(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock = Path(tmp) / 'vllm'
            mock.write_text(MOCK)
            mock.chmod(0o755)
            log = Path(tmp) / 'started'
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'], START_LOG=str(log), FAIL_PORT='8002')
            result = subprocess.run(['bash', str(ENTRYPOINT)], env=env, capture_output=True, text=True, timeout=15)
            self.assertNotEqual(result.returncode, 0)
            self.assertEqual(log.read_text().splitlines(), ['8001', 'ready 8001', '8002'])
            self.assertIn('exited during startup', result.stderr)

    def test_all_services_start_after_previous_health_check(self):
        with tempfile.TemporaryDirectory() as tmp:
            mock = Path(tmp) / 'vllm'
            mock.write_text(MOCK)
            mock.chmod(0o755)
            log = Path(tmp) / 'started'
            env = dict(os.environ, PATH=tmp + os.pathsep + os.environ['PATH'], START_LOG=str(log))
            process = subprocess.Popen(['bash', str(ENTRYPOINT)], env=env, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            try:
                deadline = time.monotonic() + 15
                while time.monotonic() < deadline:
                    if log.exists() and 'ready 8003' in log.read_text():
                        break
                    if process.poll() is not None:
                        self.fail('entrypoint exited before all services became healthy')
                    time.sleep(0.1)
                self.assertEqual(log.read_text().splitlines(), ['8001', 'ready 8001', '8002', 'ready 8002', '8003', 'ready 8003'])
            finally:
                process.terminate()
                process.wait(timeout=5)

if __name__ == '__main__':
    unittest.main()
