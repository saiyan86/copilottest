import os
import json
import asyncio
from typing import Any, Dict
from fastapi import FastAPI, Request, HTTPException, status
from fastapi.responses import JSONResponse
import httpx

# Configuration via environment variables
DEVICE_HOST = os.environ.get("ROBOTIC_ARM_HOST", "127.0.0.1")
DEVICE_PORT = int(os.environ.get("ROBOTIC_ARM_PORT", "3333"))  # RTDE/JSON-RPC port
SERVER_HOST = os.environ.get("HTTP_SERVER_HOST", "0.0.0.0")
SERVER_PORT = int(os.environ.get("HTTP_SERVER_PORT", "8080"))
DEVICE_RPC_PATH = os.environ.get("ROBOTIC_ARM_RPC_PATH", "/rpc")  # If gateway/proxy is used

DEVICE_URL = f"http://{DEVICE_HOST}:{DEVICE_PORT}{DEVICE_RPC_PATH}"

app = FastAPI()

def jsonrpc_request(method: str, params: Any = None, id_: int = 1) -> Dict[str, Any]:
    return {
        "jsonrpc": "2.0",
        "method": method,
        "params": params or {},
        "id": id_
    }

async def device_rpc_call(method: str, params: Any = None, id_: int = 1) -> Any:
    async with httpx.AsyncClient() as client:
        req_data = jsonrpc_request(method, params, id_)
        try:
            resp = await client.post(DEVICE_URL, json=req_data, timeout=5)
            resp.raise_for_status()
            data = resp.json()
            if 'error' in data:
                raise HTTPException(status_code=502, detail=data['error'])
            return data.get('result', data)
        except httpx.RequestError as e:
            raise HTTPException(status_code=502, detail=f"Device unreachable: {e}")
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"Device error: {e}")

@app.get("/status")
async def get_status():
    # Example method: get_status
    result = await device_rpc_call("get_status")
    return JSONResponse(content=result)

@app.post("/motion")
async def post_motion(request: Request):
    body = await request.json()
    # Example method: send_motion
    result = await device_rpc_call("send_motion", body)
    return JSONResponse(content=result)

@app.put("/dio")
async def put_dio(request: Request):
    body = await request.json()
    # Example method: set_digital_outputs
    result = await device_rpc_call("set_digital_outputs", body)
    return JSONResponse(content=result)

@app.post("/script")
async def post_script(request: Request):
    body = await request.json()
    # Example method: execute_lua_script
    result = await device_rpc_call("execute_lua_script", body)
    return JSONResponse(content=result)

@app.put("/speed")
async def put_speed(request: Request):
    body = await request.json()
    # Example method: set_speed
    result = await device_rpc_call("set_speed", body)
    return JSONResponse(content=result)

@app.put("/aio")
async def put_aio(request: Request):
    body = await request.json()
    # Example method: set_analog_outputs
    result = await device_rpc_call("set_analog_outputs", body)
    return JSONResponse(content=result)

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("main:app", host=SERVER_HOST, port=SERVER_PORT)