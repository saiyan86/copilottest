import os
import json
import asyncio
from http.server import BaseHTTPRequestHandler, HTTPServer
from socketserver import ThreadingMixIn
import threading
import socket

# RTDE (Real-Time Data Exchange) CLIENT IMPLEMENTATION (Simplified for Demo)
class RTDEClient:
    def __init__(self, host, port, timeout=2):
        self.host = host
        self.port = int(port)
        self.timeout = timeout
        self.lock = threading.Lock()

    def _send_jsonrpc(self, method, params=None):
        request_id = 1
        payload = {
            "jsonrpc": "2.0",
            "id": request_id,
            "method": method,
            "params": params or {}
        }
        msg = (json.dumps(payload) + "\n").encode('utf-8')
        with self.lock:
            with socket.create_connection((self.host, self.port), timeout=self.timeout) as sock:
                sock.sendall(msg)
                data = b""
                while not data.endswith(b"\n"):
                    chunk = sock.recv(4096)
                    if not chunk:
                        break
                    data += chunk
                txt = data.decode('utf-8').strip()
                try:
                    return json.loads(txt)
                except Exception:
                    return {"error": "Malformed response", "raw": txt}

    def get_status(self):
        return self._send_jsonrpc("get_status")

    def exec_script(self, script):
        return self._send_jsonrpc("exec_script", {"script": script})

    def set_speed(self, speed):
        return self._send_jsonrpc("set_speed", {"speed": speed})

    def start(self):
        return self._send_jsonrpc("start")

    def stop(self):
        return self._send_jsonrpc("stop")

    def reset(self):
        return self._send_jsonrpc("reset")

    def init(self):
        return self._send_jsonrpc("init")

    def set_mode(self, mode):
        return self._send_jsonrpc("set_mode", {"mode": mode})

    def set_io(self, io):
        return self._send_jsonrpc("set_io", io)

    def set_param(self, param):
        return self._send_jsonrpc("set_param", param)

# ENVIRONMENT VARIABLES
ROBOT_HOST = os.environ.get("ROBOT_HOST", "127.0.0.1")
ROBOT_RTDE_PORT = int(os.environ.get("ROBOT_RTDE_PORT", "8080"))
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8000"))

rtde = RTDEClient(ROBOT_HOST, ROBOT_RTDE_PORT)

# HTTP SERVER IMPLEMENTATION
class AuboRobotHandler(BaseHTTPRequestHandler):
    protocol_version = "HTTP/1.1"

    def _set_headers(self, code=200, extra=None):
        self.send_response(code)
        self.send_header('Content-Type', 'application/json')
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()

    def _parse_json(self):
        clen = int(self.headers.get('Content-Length', 0))
        if clen == 0:
            return {}
        try:
            return json.loads(self.rfile.read(clen))
        except Exception:
            return {}

    def do_GET(self):
        if self.path == "/status":
            resp = rtde.get_status()
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode())

    def do_POST(self):
        if self.path == "/exec":
            body = self._parse_json()
            script = body.get("script", "")
            if not script:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing script"}).encode())
                return
            resp = rtde.exec_script(script)
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/speed":
            body = self._parse_json()
            speed = body.get("speed", None)
            if speed is None:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing speed"}).encode())
                return
            resp = rtde.set_speed(speed)
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/start":
            resp = rtde.start()
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/stop":
            resp = rtde.stop()
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/reset":
            resp = rtde.reset()
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/init":
            resp = rtde.init()
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/mode":
            body = self._parse_json()
            mode = body.get("mode", None)
            if mode is None:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing mode"}).encode())
                return
            resp = rtde.set_mode(mode)
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/io":
            body = self._parse_json()
            if not body:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing IO data"}).encode())
                return
            resp = rtde.set_io(body)
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        elif self.path == "/param":
            body = self._parse_json()
            if not body:
                self._set_headers(400)
                self.wfile.write(json.dumps({"error": "Missing param data"}).encode())
                return
            resp = rtde.set_param(body)
            self._set_headers(200)
            self.wfile.write(json.dumps(resp).encode())
        else:
            self._set_headers(404)
            self.wfile.write(json.dumps({"error": "Not Found"}).encode())

    def log_message(self, format, *args):
        return  # Silence default logging

class ThreadedHTTPServer(ThreadingMixIn, HTTPServer):
    daemon_threads = True

def run_server():
    server = ThreadedHTTPServer((SERVER_HOST, SERVER_PORT), AuboRobotHandler)
    print(f"AUBO Robot Arm HTTP Driver running at http://{SERVER_HOST}:{SERVER_PORT}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()

if __name__ == '__main__':
    run_server()