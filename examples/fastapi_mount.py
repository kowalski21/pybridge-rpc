"""Mount PyBridge inside an existing FastAPI app.

Run:
    uvicorn examples.fastapi_mount:app --reload

Then POST to:
    /rpc/users.create
    /rpc/health.ping
    /api/version          (a regular FastAPI route alongside)
"""

from __future__ import annotations

from fastapi import FastAPI

from examples.basic import bridge
from pybridge.integrations import mount_fastapi


app = FastAPI(title="My App")


@app.get("/api/version")
async def version() -> dict:
    return {"version": "1.0.0"}


mount_fastapi(app, bridge)
