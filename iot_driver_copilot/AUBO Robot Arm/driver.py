import os
import json
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
import socket
import threading

# Environment configuration
DEVICE_HOST = os.environ.get("AUBO_DEVICE_HOST", "127.0.0.1")
DEVICE_PORT = int(os.environ.get("AUBO_DEVICE_PORT", "8899"))  # for JSON-RPC/TCP commands
SERVER_HOST = os.environ.get("AUBO_DRIVER_HTTP_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("AUBO_DRIVER_HTTP_PORT", "8080"))

# Helper for JSON-RPC over TCP
def send_json_rpc(method, params):
    req = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    msg = json.dumps(req).encode("utf-8")
    msg_len = len(msg).to_bytes(4, byteorder='big')
    response = b""
    with socket.create_connection((DEVICE_HOST, DEVICE_PORT), timeout=3) as sock:
        sock.sendall(msg_len + msg)
        # Protocol: read 4 bytes for length, then that many bytes for payload
        header = sock.recv(4)
        if len(header) < 4:
            raise RuntimeError("Invalid response from device")
        resp_len = int.from_bytes(header, byteorder='big')
        while len(response) < resp_len:
            chunk = sock.recv(resp_len - len(response))
            if not chunk:
                break
            response += chunk
    return json.loads(response.decode("utf-8"))

class AuboDriverHTTPRequestHandler(BaseHTTPRequestHandler):
    def _set_json_response(self, code=200):
        self.send_response(code)
        self.send_header('Content-type', 'application/json')
        self.end_headers()

    def _handle_json_rpc(self, rpc_method, required_keys=None):
        content_len = int(self.headers.get('Content-Length', 0))
        if content_len == 0:
            self._set_json_response(400)
            self.wfile.write(json.dumps({"error": "Empty body"}).encode())
            return
        try:
            data = json.loads(self.rfile.read(content_len))
        except Exception:
            self._set_json_response(400)
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode())
            return

        if required_keys:
            missing = [k for k in required_keys if k not in data]
            if missing:
                self._set_json_response(400)
                self.wfile.write(json.dumps({"error": f"Missing keys: {missing}"}).encode())
                return

        try:
            resp = send_json_rpc(rpc_method, data)
            self._set_json_response()
            self.wfile.write(json.dumps(resp.get("result", resp)).encode())
        except Exception as e:
            self._set_json_response(500)
            self.wfile.write(json.dumps({"error": str(e)}).encode())

    def do_POST(self):
        path = urlparse(self.path).path
        if path == "/ik":
            # Expected: { "pose": [x, y, z, rx, ry, rz] }
            self._handle_json_rpc("compute_inverse_kinematics", required_keys=["pose"])
        elif path == "/payload":
            # Expected: { "weight": float, "center_of_mass": [x, y, z] }
            self._handle_json_rpc("set_payload", required_keys=["weight", "center_of_mass"])
        elif path == "/simul":
            # Expected: { "enable": bool }
            self._handle_json_rpc("set_simulation_mode", required_keys=["enable"])
        elif path == "/io":
            # Expected: { "type": "digital"/"analog", "channel": int, "value": int/float }
            self._handle_json_rpc("set_io_output", required_keys=["type", "channel", "value"])
        elif path == "/speed":
            # Expected: { "speed": float }
            self._handle_json_rpc("set_speed_slider", required_keys=["speed"])
        elif path == "/power":
            # Expected: { "on": bool }
            self._handle_json_rpc("set_power_state", required_keys=["on"])
        elif path == "/guide":
            # Expected: { "enable": bool }
            self._handle_json_rpc("set_handguide_mode", required_keys=["enable"])
        else:
            self._set_json_response(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode())

    def do_GET(self):
        # Optionally, a simple health check or metadata endpoint
        if self.path == "/":
            self.send_response(200)
            self.send_header('Content-type', 'application/json')
            self.end_headers()
            info = {
                "device": "AUBO Robot Arm",
                "model": "AUBO series",
                "manufacturer": "AUBO",
                "api": [
                    {"method": "POST", "path": "/ik", "desc": "Inverse kinematics"},
                    {"method": "POST", "path": "/payload", "desc": "Set payload"},
                    {"method": "POST", "path": "/simul", "desc": "Simulation mode"},
                    {"method": "POST", "path": "/io", "desc": "IO control"},
                    {"method": "POST", "path": "/speed", "desc": "Speed slider"},
                    {"method": "POST", "path": "/power", "desc": "Power on/off"},
                    {"method": "POST", "path": "/guide", "desc": "Handguide mode"},
                ]
            }
            self.wfile.write(json.dumps(info).encode())
        else:
            self.send_response(404)
            self.end_headers()

def run_server():
    server = HTTPServer((SERVER_HOST, SERVER_PORT), AuboDriverHTTPRequestHandler)
    print(f"AUBO driver HTTP server running at http://{SERVER_HOST}:{SERVER_PORT}/")
    server.serve_forever()

if __name__ == "__main__":
    run_server()