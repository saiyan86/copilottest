import os
import json
import asyncio
from typing import Optional
from fastapi import FastAPI, Request, Response, HTTPException, status
from fastapi.responses import JSONResponse
from pydantic import BaseModel
import httpx

# Environment variables for configuration
AUBO_HOST = os.environ.get('AUBO_HOST', '127.0.0.1')
AUBO_PORT = int(os.environ.get('AUBO_PORT', '8080'))
AUBO_RTDE_HOST = os.environ.get('AUBO_RTDE_HOST', AUBO_HOST)
AUBO_RTDE_PORT = int(os.environ.get('AUBO_RTDE_PORT', '30004'))  # example default port for RTDE (may differ)
AUBO_RPC_HOST = os.environ.get('AUBO_RPC_HOST', AUBO_HOST)
AUBO_RPC_PORT = int(os.environ.get('AUBO_RPC_PORT', '8081'))     # example default port for JSON-RPC
AUBO_SCRIPT_HOST = os.environ.get('AUBO_SCRIPT_HOST', AUBO_HOST)
AUBO_SCRIPT_PORT = int(os.environ.get('AUBO_SCRIPT_PORT', '30003'))  # example default port for script execution

# HTTP server configuration
SERVER_HOST = os.environ.get('SERVER_HOST', '0.0.0.0')
SERVER_PORT = int(os.environ.get('SERVER_PORT', '8000'))

app = FastAPI(title="AUBO Robotic Arm HTTP Proxy Driver")

# --- Request/Response Models ---

class MotionCommand(BaseModel):
    waypoints: list
    velocity: Optional[float] = None
    acceleration: Optional[float] = None
    # Add more fields as needed

class DigitalOutputCommand(BaseModel):
    outputs: dict

class AnalogOutputCommand(BaseModel):
    outputs: dict

class SpeedCommand(BaseModel):
    speed: float

class ScriptCommand(BaseModel):
    script: str

# --- Utility Functions ---

async def aubo_json_rpc(method: str, params: dict):
    url = f"http://{AUBO_RPC_HOST}:{AUBO_RPC_PORT}/rpc"
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": method,
        "params": params or {}
    }
    async with httpx.AsyncClient() as client:
        r = await client.post(url, json=payload, timeout=10)
        r.raise_for_status()
        resp = r.json()
        if "error" in resp:
            raise HTTPException(status_code=500, detail=resp["error"])
        return resp.get("result")

# --- API Endpoints ---

@app.get("/status", tags=["Status"])
async def get_status():
    # RTDE (Real-Time Data Exchange) is typically a binary protocol, but some AUBO models may expose status via JSON-RPC
    # We'll use JSON-RPC here for status if available
    try:
        result = await aubo_json_rpc("get_status", {})
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to fetch status: {str(e)}")

@app.post("/motion", tags=["Motion"])
async def post_motion(cmd: MotionCommand):
    try:
        result = await aubo_json_rpc("set_motion", cmd.dict())
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to send motion command: {str(e)}")

@app.put("/dio", tags=["Digital I/O"])
async def put_dio(cmd: DigitalOutputCommand):
    try:
        result = await aubo_json_rpc("set_digital_outputs", cmd.dict())
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set digital outputs: {str(e)}")

@app.put("/aio", tags=["Analog I/O"])
async def put_aio(cmd: AnalogOutputCommand):
    try:
        result = await aubo_json_rpc("set_analog_outputs", cmd.dict())
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set analog outputs: {str(e)}")

@app.put("/speed", tags=["Speed"])
async def put_speed(cmd: SpeedCommand):
    try:
        result = await aubo_json_rpc("set_speed", cmd.dict())
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to set speed: {str(e)}")

@app.post("/script", tags=["Lua Script"])
async def post_script(cmd: ScriptCommand):
    # For executing Lua scripts, some AUBO controllers accept JSON-RPC, others may require TCP
    try:
        result = await aubo_json_rpc("run_lua_script", cmd.dict())
        return JSONResponse(content=result)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to execute script: {str(e)}")

# --- Run server ---

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT, reload=False)