"""Loopback-only A2A fixture, deliberately not codex-a2a.

Mode durable persists tasks; lost mode deliberately discards them on restart.
"""
import json
import os
from pathlib import Path
import sys
from http.server import BaseHTTPRequestHandler, HTTPServer

root, port, mode = Path(sys.argv[1]), int(sys.argv[2]), sys.argv[3]


def persist(path, value):
    with path.open('w') as f:
        json.dump(value, f)
        f.flush()
        os.fsync(f.fileno())


class Handler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        pass

    def do_POST(self):
        body = json.loads(self.rfile.read(int(self.headers['Content-Length'])))
        with (root / 'calls.jsonl').open('a') as f:
            f.write(json.dumps(body) + '\n')
            f.flush()
            os.fsync(f.fileno())
        rid = body['id']
        if body['method'] == 'SendStreamingMessage':
            task = {'id': 'remote-1', 'contextId': 'ctx-1', 'status': {'state': 'TASK_STATE_WORKING'}}
            if mode != 'lost':
                persist(root / 'task.json', task)
            if mode == 'before-ack':
                self.close_connection = True
                return
            if mode == 'headers':
                import time
                for byte in b'HTTP/1.1 200 OK\r\nContent-Type: text/event-stream\r\n\r\n':
                    self.wfile.write(bytes([byte]))
                    self.wfile.flush()
                    time.sleep(.1)
                return
            if mode == 'redirect':
                self.send_response(307)
                self.send_header('Location', f'http://127.0.0.1:{self.server.server_port}/credential-trap')
                self.end_headers()
                return
            self.send_response(200)
            self.send_header('Content-Type', 'text/event-stream')
            self.end_headers()
            self.wfile.write(('data: ' + json.dumps({'jsonrpc': '2.0', 'id': rid, 'result': {'task': task}}) + '\n\n').encode())
            self.wfile.flush()
            if mode == 'drip':
                import time
                for _ in range(160):
                    self.wfile.write(b': heartbeat\n\n')
                    self.wfile.flush()
                    time.sleep(.05)
            if mode == 'hold':
                # Test kills the client/server only after it sees the durable acknowledgement.
                import time
                time.sleep(30)
            return
        assert body['method'] == 'GetTask'
        assert body['params'] == {'id': 'remote-1'}
        if mode == 'bad-get':
            response = {'jsonrpc': '2.0', 'id': rid, 'error': []}
        elif (root / 'task.json').exists():
            task = json.loads((root / 'task.json').read_text())
            task['status']['state'] = 'TASK_STATE_COMPLETED'
            task['artifacts'] = [{'artifactId': 'answer', 'parts': [{'text': 'durable fixture result'}]}]
            response = {'jsonrpc': '2.0', 'id': rid, 'result': task}
        else:
            response = {'jsonrpc': '2.0', 'id': rid, 'error': {'code': -32001, 'message': 'Task not found'}}
        self.send_response(200)
        self.send_header('Content-Type', 'application/json')
        self.end_headers()
        self.wfile.write(json.dumps(response).encode())


HTTPServer.allow_reuse_address = True
server = HTTPServer(('127.0.0.1', port), Handler)
print(server.server_port, flush=True)
server.serve_forever()
