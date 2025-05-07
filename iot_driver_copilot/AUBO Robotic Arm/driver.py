import os
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# Configuration from environment variables
ROBOT_HOST = os.environ.get('AUBO_ROBOT_IP', '127.0.0.1')
ROBOT_PORT = int(os.environ.get('AUBO_ROBOT_PORT', '8899'))  # Default AUBO JSON-RPC port, change as needed
SERVER_HOST = os.environ.get('HTTP_SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('HTTP_SERVER_PORT', '8080'))

# Helper to generate unique JSON-RPC IDs
def _rpc_id_gen():
    n = 1
    while True:
        yield n
        n += 1
_rpc_id_iter = _rpc_id_gen()

# TCP/JSON-RPC2.0 Client (synchronous, per-request)
def aubo_jsonrpc_call(method, params=None):
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "id": next(_rpc_id_iter)
    }
    if params is not None:
        payload["params"] = params
    data = json.dumps(payload).encode('utf-8')

    s = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
    s.settimeout(5)
    try:
        s.connect((ROBOT_HOST, ROBOT_PORT))
        s.sendall(data + b'\n')
        resp = b''
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            resp += chunk
            if b'\n' in chunk:
                break
        # Handle multiple responses per line, only pick the first full JSON object
        resp_str = resp.decode('utf-8').split('\n')[0].strip()
        if not resp_str:
            raise Exception("No response from robot")
        return json.loads(resp_str)
    finally:
        s.close()

# Robot API Mappings
def robot_reset_errors():
    return aubo_jsonrpc_call('reset_error')

def robot_power(state):
    assert state in ('on', 'off')
    return aubo_jsonrpc_call('power', {"state": state})

def robot_startup():
    return aubo_jsonrpc_call('startup')

def robot_execute_traj(joints, speed=1.0, accel=1.0):
    # joints: list of joint positions (rad), speed/accel: float
    return aubo_jsonrpc_call('execute_trajectory', {"joints": joints, "speed": speed, "accel": accel})

def robot_status():
    return aubo_jsonrpc_call('get_status')

# HTTP Server
class RobotHTTPRequestHandler(BaseHTTPRequestHandler):
    server_version = "AUBODriverHTTP/1.0"

    def _set_json_response(self, code=200):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        self.send_header('Access-Control-Allow-Origin', '*')
        self.end_headers()

    def _parse_json(self):
        content_length = int(self.headers.get('Content-Length', 0))
        if content_length == 0:
            return None
        raw_body = self.rfile.read(content_length)
        try:
            return json.loads(raw_body)
        except Exception:
            return None

    def do_GET(self):
        parsed = urlparse(self.path)
        if parsed.path == '/status':
            try:
                result = robot_status()
                self._set_json_response(200)
                self.wfile.write(json.dumps({"result": result}).encode('utf-8'))
            except Exception as e:
                self._set_json_response(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
        else:
            self.send_response(404)
            self.end_headers()
    
    def do_POST(self):
        parsed = urlparse(self.path)
        # /reset
        if parsed.path == '/reset':
            try:
                result = robot_reset_errors()
                self._set_json_response(200)
                self.wfile.write(json.dumps({"result": result}).encode('utf-8'))
            except Exception as e:
                self._set_json_response(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # /power
        if parsed.path == '/power':
            data = self._parse_json()
            state = (data or {}).get('state')
            if state not in ('on', 'off'):
                self._set_json_response(400)
                self.wfile.write(json.dumps({"error": "Missing or invalid 'state', must be 'on' or 'off'"}).encode('utf-8'))
                return
            try:
                result = robot_power(state)
                self._set_json_response(200)
                self.wfile.write(json.dumps({"result": result}).encode('utf-8'))
            except Exception as e:
                self._set_json_response(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # /startup
        if parsed.path == '/startup':
            try:
                result = robot_startup()
                self._set_json_response(200)
                self.wfile.write(json.dumps({"result": result}).encode('utf-8'))
            except Exception as e:
                self._set_json_response(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        # /traj
        if parsed.path == '/traj':
            data = self._parse_json()
            joints = (data or {}).get('joints')
            speed = (data or {}).get('speed', 1.0)
            accel = (data or {}).get('accel', 1.0)
            if not (isinstance(joints, list) and all(isinstance(j, (int, float)) for j in joints)):
                self._set_json_response(400)
                self.wfile.write(json.dumps({"error": "Missing or invalid 'joints': must be a list of numbers"}).encode('utf-8'))
                return
            try:
                result = robot_execute_traj(joints, speed, accel)
                self._set_json_response(200)
                self.wfile.write(json.dumps({"result": result}).encode('utf-8'))
            except Exception as e:
                self._set_json_response(500)
                self.wfile.write(json.dumps({"error": str(e)}).encode('utf-8'))
            return

        self.send_response(404)
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(200)
        self.send_header('Access-Control-Allow-Origin', '*')
        self.send_header('Access-Control-Allow-Methods', 'GET, POST, OPTIONS')
        self.send_header('Access-Control-Allow-Headers', 'Content-Type')
        self.end_headers()

def run_server():
    httpd = HTTPServer((SERVER_HOST, SERVER_PORT), RobotHTTPRequestHandler)
    print(f"Starting HTTP server on {SERVER_HOST}:{SERVER_PORT} for AUBO Robot...")
    httpd.serve_forever()

if __name__ == '__main__':
    run_server()