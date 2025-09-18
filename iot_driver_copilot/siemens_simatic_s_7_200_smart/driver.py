import os
import json
import uuid
from typing import Optional, Dict, Any
from fastapi import FastAPI, Request, Response, HTTPException, status, Depends
from fastapi.responses import JSONResponse
import httpx

# Environment variables for configuration
DEVICE_IP = os.environ.get("DEVICE_IP", "127.0.0.1")
DEVICE_PORT = os.environ.get("DEVICE_PORT", "80")
DEVICE_PROTOCOL = os.environ.get("DEVICE_PROTOCOL", "http")
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8080"))
DEVICE_USER = os.environ.get("DEVICE_USER", "")
DEVICE_PASS = os.environ.get("DEVICE_PASS", "")
DEVICE_BASE_PATH = os.environ.get("DEVICE_BASE_PATH", "/jsonrpc")

DEVICE_URL = f"{DEVICE_PROTOCOL}://{DEVICE_IP}:{DEVICE_PORT}{DEVICE_BASE_PATH}"

app = FastAPI()

# In-memory session storage
sessions: Dict[str, Dict[str, Any]] = {}

def get_auth_token(session_id: Optional[str]) -> Optional[str]:
    if session_id and session_id in sessions:
        return sessions[session_id].get("token")
    return None

async def jsonrpc_request(method: str, params: Any = None, token: Optional[str] = None) -> Any:
    headers = {"Content-Type": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"
    payload = {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": str(uuid.uuid4())
    }
    async with httpx.AsyncClient() as client:
        resp = await client.post(DEVICE_URL, headers=headers, json=payload, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        if "error" in data:
            raise HTTPException(status_code=400, detail=data["error"])
        return data.get("result")

def require_session(request: Request):
    session_id = request.headers.get("X-Session-Id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found.")
    return session_id

@app.post("/login")
async def login(request: Request):
    try:
        body = await request.json()
    except Exception:
        body = {}
    username = body.get("username", DEVICE_USER)
    password = body.get("password", DEVICE_PASS)
    if not username or not password:
        raise HTTPException(status_code=400, detail="Username and password required")
    result = await jsonrpc_request("login", {"username": username, "password": password})
    token = result.get("token")
    if not token:
        raise HTTPException(status_code=401, detail="Authentication failed")
    session_id = str(uuid.uuid4())
    sessions[session_id] = {"token": token, "username": username}
    return {"session_id": session_id, "token": token}

@app.post("/logout")
async def logout(request: Request):
    session_id = request.headers.get("X-Session-Id")
    if session_id and session_id in sessions:
        token = sessions[session_id]["token"]
        try:
            await jsonrpc_request("logout", token=token)
        except Exception:
            pass
        del sessions[session_id]
    return {"message": "Logged out"}

@app.get("/perm")
async def perm(session_id: str = Depends(require_session)):
    token = get_auth_token(session_id)
    result = await jsonrpc_request("get_permission", token=token)
    return result

@app.get("/browse")
async def browse(session_id: str = Depends(require_session)):
    token = get_auth_token(session_id)
    result = await jsonrpc_request("browse", token=token)
    return result

@app.get("/read")
async def read(request: Request):
    session_id = request.headers.get("X-Session-Id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found.")
    token = sessions[session_id]["token"]
    params = dict(request.query_params)
    result = await jsonrpc_request("read", params=params, token=token)
    return result

@app.post("/write")
async def write(request: Request):
    session_id = request.headers.get("X-Session-Id")
    if not session_id or session_id not in sessions:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Session not found.")
    token = sessions[session_id]["token"]
    body = await request.json()
    result = await jsonrpc_request("write", params=body, token=token)
    return result

if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)
