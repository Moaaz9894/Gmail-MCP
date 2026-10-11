import asyncio
from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv
load_dotenv()

import uvicorn
from fastapi import FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from agent import Agent
from mcp_client import MCPGmail

state = {}
lock = asyncio.Lock()


@asynccontextmanager
async def lifespan(app):
    mcp = MCPGmail()
    await mcp.start()
    state["agent"] = Agent(mcp)
    yield
    await mcp.stop()


app = FastAPI(lifespan=lifespan)


class Chat(BaseModel):
    message: str


class Confirm(BaseModel):
    approve: bool


@app.get("/")
def index():
    return FileResponse(Path(__file__).parent / "static" / "index.html")


@app.post("/api/chat")
async def chat(body: Chat):
    async with lock:
        return await state["agent"].send(body.message)


@app.post("/api/confirm")
async def confirm(body: Confirm):
    async with lock:
        return await state["agent"].resume(body.approve)


@app.post("/api/reset")
async def reset():
    async with lock:
        state["agent"].reset()
    return {"ok": True}


if __name__ == "__main__":
    # no reload=True: it breaks subprocess (MCP stdio) on Windows
    uvicorn.run(app, host="127.0.0.1", port=8000)
