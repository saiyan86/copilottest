import os
import json
import socket
import threading
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs

# Environment variable configuration
ROBOT_IP = os.environ.get("AUBO_ROBOT_IP", "127.0.0.1")
ROBOT_PORT = int(os.environ.get("AUBO_ROBOT_PORT", "8899"))
SERVER_HOST = os.environ.get("HTTP_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("HTTP_SERVER_PORT", "8080"))
TCP_TIMEOUT = float(os.environ.get("AUBO_TCP_TIMEOUT", "3.0"))

DEVICE_INFO = {
    "device_name": "AUBO Robot System",
    "device_model": "AUBO",
    "manufacturer": "AUBO Robotics",
    "device_type": "Industrial Robot Arm",
    "supported_protocols": ["TCP", "JSON-RPC 2.0", "RTDE", "Modbus"]
}

def tcp_send_recv(req_json):
    with socket.create_connection((ROBOT_IP, ROBOT_PORT), timeout=TCP_TIMEOUT) as s:
        s.sendall(json.dumps(req_json).encode('utf-8') + b"\n")
        data = b""
        while True:
            chunk = s.recv(4096)
            if not chunk:
                break
            data += chunk
            if b"\n" in chunk:
                break
    try:
        return json.loads(data.decode('utf-8').strip())
    except Exception:
        return {"error": "Invalid response from robot", "raw": data.decode("utf-8", "ignore")}

class Handler(BaseHTTPRequestHandler):
    def _set_headers(self, status=200, content_type="application/json"):
        self.send_response(status)
        self.send_header("Content-type", content_type)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.end_headers()

    def do_OPTIONS(self):
        self.send_response(204)
        self.send_header("Access-Control-Allow-Origin", "*")
        self.send_header("Access-Control-Allow-Methods", "GET, POST, OPTIONS")
        self.send_header("Access-Control-Allow-Headers", "Content-Type")
        self.end_headers()

    def do_GET(self):
        parsed_path = urlparse(self.path)
        if parsed_path.path == "/info":
            self._set_headers()
            self.wfile.write(json.dumps(DEVICE_INFO).encode("utf-8"))
            return
        elif parsed_path.path == "/status":
            req_json = {
                "jsonrpc": "2.0",
                "method": "get_status",
                "params": {},
                "id": 1
            }
            res = tcp_send_recv(req_json)
            self._set_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode("utf-8"))

    def do_POST(self):
        content_length = int(self.headers.get('Content-Length', 0))
        body = self.rfile.read(content_length)
        try:
            data = json.loads(body.decode("utf-8"))
        except Exception:
            self._set_headers(400)
            self.wfile.write(json.dumps({"error": "Invalid JSON"}).encode("utf-8"))
            return

        parsed_path = urlparse(self.path)
        if parsed_path.path == "/io":
            req_json = {
                "jsonrpc": "2.0",
                "method": "set_io",
                "params": data,
                "id": 2
            }
            res = tcp_send_recv(req_json)
            self._set_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return
        elif parsed_path.path == "/motion":
            req_json = {
                "jsonrpc": "2.0",
                "method": "motion_command",
                "params": data,
                "id": 3
            }
            res = tcp_send_recv(req_json)
            self._set_headers()
            self.wfile.write(json.dumps(res).encode("utf-8"))
            return
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not found"}).encode("utf-8"))

def run_server():
    server = HTTPServer((SERVER_HOST, SERVER_PORT), Handler)
    print(f"Starting HTTP server at http://{SERVER_HOST}:{SERVER_PORT}")
    server.serve_forever()

if __name__ == "__main__":
    run_server()
