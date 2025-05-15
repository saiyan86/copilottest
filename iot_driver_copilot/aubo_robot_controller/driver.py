import os
import asyncio
import json
from typing import Dict, Any
from fastapi import FastAPI, Request, Response, status
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
import httpx

# Configuration from environment variables
ROBOT_HOST = os.environ.get("ROBOT_HOST", "127.0.0.1")
ROBOT_RTDE_PORT = int(os.environ.get("ROBOT_RTDE_PORT", "30004"))
ROBOT_JSONRPC_PORT = int(os.environ.get("ROBOT_JSONRPC_PORT", "8080"))
SERVER_HOST = os.environ.get("SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("SERVER_PORT", "8000"))

app = FastAPI()

# RTDE Real-Time Data Streamer
async def rtde_status_stream():
    reader, writer = await asyncio.open_connection(ROBOT_HOST, ROBOT_RTDE_PORT)
    try:
        # RTDE handshake/init (simplified, as actual implementation may require more steps)
        # Send RTDE protocol handshake (e.g., 'RTDE\x00\x01')
        # Here, we simply start reading binary packets and parse them as demo
        while True:
            data = await reader.read(4096)
            if not data:
                break
            # For demo, simply yield raw data as a hex string (should parse per RTDE spec in production)
            payload = {"raw": data.hex()}
            yield f"data: {json.dumps(payload)}\n\n"
            await asyncio.sleep(0.05)
    finally:
        writer.close()
        await writer.wait_closed()

async def parse_rtde_status():
    # This function should parse the RTDE packet format and extract relevant fields.
    # Here, we mock the status for demonstration purposes.
    # In production, implement parsing according to AUBO RTDE documentation.
    reader, writer = await asyncio.open_connection(ROBOT_HOST, ROBOT_RTDE_PORT)
    try:
        # Example: read a single RTDE packet and parse
        data = await reader.read(4096)
        # Mock parsed data
        status = {
            "joint_positions": [0.1, 0.2, 0.3, 0.4, 0.5, 0.6],
            "joint_velocities": [0.0, 0.0, 0.0, 0.0, 0.0, 0.0],
            "safety_mode": "NORMAL",
            "robot_mode": "RUNNING",
            "error_codes": [],
            "timestamp": asyncio.get_event_loop().time()
        }
        return status
    finally:
        writer.close()
        await writer.wait_closed()

# JSON-RPC 2.0 client
async def jsonrpc_call(method: str, params: Any) -> Any:
    url = f"http://{ROBOT_HOST}:{ROBOT_JSONRPC_PORT}/jsonrpc"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, timeout=5.0)
        r.raise_for_status()
        resp = r.json()
        if "error" in resp:
            raise Exception(resp["error"])
        return resp.get("result", {})

# API Models
class IOCommand(BaseModel):
    digital_outputs: Dict[int, int] = {}
    analog_outputs: Dict[int, float] = {}

class ToolCommand(BaseModel):
    action: str
    parameters: Dict[str, Any] = {}

class MoveCommand(BaseModel):
    joint_positions: list
    speed: float = 0.5

class ConfigCommand(BaseModel):
    payload: float = None
    speed_scaling: float = None
    calibration: Dict[str, Any] = {}

# API Endpoints

@app.get("/status")
async def get_status(request: Request):
    # For real-time, support SSE streaming if requested, else just return current status
    if request.headers.get("accept") == "text/event-stream":
        return StreamingResponse(rtde_status_stream(), media_type="text/event-stream")
    else:
        status = await parse_rtde_status()
        return JSONResponse(content=status)

@app.post("/io")
async def post_io(cmd: IOCommand):
    # Forward IO command via JSON-RPC
    params = {
        "digital_outputs": cmd.digital_outputs,
        "analog_outputs": cmd.analog_outputs
    }
    try:
        result = await jsonrpc_call("set_io", params)
        return JSONResponse(content={"success": True, "result": result})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

@app.post("/tool")
async def post_tool(cmd: ToolCommand):
    # Forward tool command via JSON-RPC
    params = {
        "action": cmd.action,
        "parameters": cmd.parameters
    }
    try:
        result = await jsonrpc_call("tool_command", params)
        return JSONResponse(content={"success": True, "result": result})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

@app.post("/move")
async def post_move(cmd: MoveCommand):
    # Forward move command via JSON-RPC
    params = {
        "joint_positions": cmd.joint_positions,
        "speed": cmd.speed
    }
    try:
        result = await jsonrpc_call("move_joint", params)
        return JSONResponse(content={"success": True, "result": result})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

@app.put("/config")
async def put_config(cmd: ConfigCommand):
    params = {}
    if cmd.payload is not None:
        params["payload"] = cmd.payload
    if cmd.speed_scaling is not None:
        params["speed_scaling"] = cmd.speed_scaling
    if cmd.calibration:
        params["calibration"] = cmd.calibration
    try:
        result = await jsonrpc_call("set_config", params)
        return JSONResponse(content={"success": True, "result": result})
    except Exception as e:
        return JSONResponse(content={"success": False, "error": str(e)}, status_code=500)

# Launch with: uvicorn this_file:app --host $SERVER_HOST --port $SERVER_PORT
if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)