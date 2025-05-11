import os
import json
import asyncio
from typing import Dict, Any
from fastapi import FastAPI, Request, HTTPException
from fastapi.responses import JSONResponse
import uvicorn
import httpx

# Environment Variables
ROBOT_IP = os.environ.get('AUBO_ROBOT_IP', '127.0.0.1')
ROBOT_PORT = int(os.environ.get('AUBO_ROBOT_PORT', 8899))
SERVER_HOST = os.environ.get('HTTP_SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('HTTP_SERVER_PORT', 8000))
ROBOT_JSONRPC_PATH = os.environ.get('AUBO_JSONRPC_PATH', '/jsonrpc')

app = FastAPI()

class AuboJsonRpcClient:
    def __init__(self, ip: str, port: int, path: str):
        self.base_url = f"http://{ip}:{port}{path}"
        self._id = 1

    async def call(self, method: str, params: Dict[str, Any] = None):
        payload = {
            "jsonrpc": "2.0",
            "id": self._id,
            "method": method
        }
        if params is not None:
            payload["params"] = params
        self._id += 1

        async with httpx.AsyncClient(timeout=5) as client:
            try:
                resp = await client.post(self.base_url, json=payload)
            except Exception as e:
                raise HTTPException(status_code=502, detail=f"Error contacting robot: {str(e)}")

        if resp.status_code != 200:
            raise HTTPException(status_code=resp.status_code, detail="Robot API error")
        try:
            data = resp.json()
        except Exception:
            raise HTTPException(status_code=502, detail="Invalid response from robot")
        if 'error' in data:
            raise HTTPException(status_code=500, detail=data['error'])
        return data.get('result')

robot = AuboJsonRpcClient(ROBOT_IP, ROBOT_PORT, ROBOT_JSONRPC_PATH)

@app.get("/status")
async def get_status():
    # Aggregate multiple robot status fields
    try:
        result = await robot.call("getRobotStatus")
    except HTTPException as e:
        raise
    # Example result aggregation (depends on actual robot JSON-RPC API)
    # result should contain: joint positions, speeds, temp, voltage, accelerometer, error codes, motion progress, etc.
    # If needed, call more endpoints and merge results
    return JSONResponse(result)

@app.post("/io")
async def io_control(request: Request):
    """
    Accepts JSON body:
    {
        "action": "read"|"write",
        "type": "digital"|"analog",
        "channel": int,
        "value": optional (for write)
    }
    """
    try:
        body = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    action = body.get("action")
    io_type = body.get("type")
    channel = body.get("channel")
    value = body.get("value", None)

    if action not in ("read", "write") or io_type not in ("digital", "analog") or channel is None:
        raise HTTPException(status_code=400, detail="Missing required fields")

    if action == "read":
        method = "readDigitalIO" if io_type == "digital" else "readAnalogIO"
        params = {"channel": channel}
        try:
            result = await robot.call(method, params)
        except HTTPException as e:
            raise
        return JSONResponse({"type": io_type, "channel": channel, "value": result})
    else:  # write
        if value is None:
            raise HTTPException(status_code=400, detail="Missing 'value' for write action")
        method = "writeDigitalIO" if io_type == "digital" else "writeAnalogIO"
        params = {"channel": channel, "value": value}
        try:
            result = await robot.call(method, params)
        except HTTPException as e:
            raise
        return JSONResponse({"type": io_type, "channel": channel, "written": value, "result": result})

@app.post("/move")
async def move(request: Request):
    """
    Accepts JSON body:
    {
        "joint_positions": [float, ...],   # optional
        "speeds": [float, ...],            # optional
        "control_mode": str                # optional
    }
    """
    try:
        payload = await request.json()
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid JSON")

    joint_positions = payload.get("joint_positions")
    speeds = payload.get("speeds")
    control_mode = payload.get("control_mode")

    params = {}
    if joint_positions is not None:
        params["joint_positions"] = joint_positions
    if speeds is not None:
        params["speeds"] = speeds
    if control_mode is not None:
        params["control_mode"] = control_mode

    if not params:
        raise HTTPException(status_code=400, detail="No motion parameters specified")

    try:
        result = await robot.call("moveJoints", params)
    except HTTPException as e:
        raise
    return JSONResponse({"status": "move command sent", "result": result})

if __name__ == "__main__":
    uvicorn.run(app, host=SERVER_HOST, port=SERVER_PORT)