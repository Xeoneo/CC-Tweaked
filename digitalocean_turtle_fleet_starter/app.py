"""Stage 1: read-only telemetry backend for CC:Tweaked turtles.
No movement or mining commands are implemented or accepted.
"""
from __future__ import annotations

import asyncio
import hmac
import json
import os
from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, Header, HTTPException, WebSocket, WebSocketDisconnect, status
from fastapi.responses import FileResponse

ROOT = Path(__file__).resolve().parent
HEARTBEAT_AGE_SECONDS = 35


def valid_token(value: str | None, expected: str) -> bool:
    return bool(value and expected and hmac.compare_digest(value, expected))


class MemoryStore:
    """Local-test store only. Cloud deployments should use PostgresStore."""
    def __init__(self):
        self.rows: dict[int, dict] = {}
        self.lock = asyncio.Lock()

    async def upsert(self, row: dict):
        async with self.lock:
            self.rows[row["id"]] = {**row, "last_seen": datetime.now(timezone.utc).isoformat()}

    async def list(self) -> list[dict]:
        async with self.lock:
            return [dict(self.rows[k]) for k in sorted(self.rows)]

    async def close(self):
        return None


class PostgresStore:
    def __init__(self, pool):
        self.pool = pool

    @classmethod
    async def connect(cls, url: str):
        # Keep asyncpg optional for local tests; it is included in requirements.txt.
        import asyncpg
        pool = await asyncpg.create_pool(dsn=url, min_size=1, max_size=4, timeout=20)
        async with pool.acquire() as con:
            await con.execute('''
                CREATE TABLE IF NOT EXISTS fleet_turtles (
                  id integer PRIMARY KEY,
                  label text NOT NULL,
                  state jsonb NOT NULL,
                  last_seen timestamptz NOT NULL DEFAULT now()
                )
            ''')
        return cls(pool)

    async def upsert(self, row: dict):
        async with self.pool.acquire() as con:
            await con.execute('''
                INSERT INTO fleet_turtles (id, label, state, last_seen)
                VALUES ($1, $2, $3::jsonb, NOW())
                ON CONFLICT (id) DO UPDATE SET
                    label = EXCLUDED.label,
                    state = EXCLUDED.state,
                    last_seen = NOW()
            ''', row["id"], row["label"], json.dumps(row))

    async def list(self) -> list[dict]:
        async with self.pool.acquire() as con:
            records = await con.fetch('SELECT id,label,state,last_seen FROM fleet_turtles ORDER BY id')
        rows = []
        for rec in records:
            state = rec['state']
            if isinstance(state, str):
                state = json.loads(state)
            rows.append({**state, "id": rec['id'], "label": rec['label'],
                         "last_seen": rec['last_seen'].isoformat()})
        return rows

    async def close(self):
        await self.pool.close()


def sanitized_status(msg: dict, turtle_id: int, label: str) -> dict:
    # Explicit allowlist: clients cannot submit arbitrary commands or server fields.
    pos = msg.get("pos")
    if not isinstance(pos, dict) or not all(isinstance(pos.get(k), (int, float))
                                            and not isinstance(pos.get(k), bool)
                                            and abs(pos[k]) < 30_000_000
                                            for k in ('x', 'y', 'z')):
        pos = None
    else:
        pos = {key: round(pos[key]) for key in ('x', 'y', 'z')}
    fuel = msg.get("fuel")
    if not (isinstance(fuel, int) and not isinstance(fuel, bool) and fuel >= 0) and fuel != 'unlimited':
        fuel = None
    slots = msg.get("slots")
    if not isinstance(slots, int) or isinstance(slots, bool) or not 0 <= slots <= 16:
        slots = None
    return {
        "id": turtle_id, "label": label, "pos": pos,
        "fuel": fuel, "slots": slots,
        "dimension": str(msg.get("dimension", "unknown"))[:40],
        "mode": "telemetry-only",
    }


@asynccontextmanager
async def lifespan(app: FastAPI):
    admin = os.environ.get('ADMIN_KEY', '')
    fleet = os.environ.get('FLEET_KEY', '')
    if len(admin) < 24 or len(fleet) < 24 or admin == fleet:
        raise RuntimeError('Set different ADMIN_KEY and FLEET_KEY values of at least 24 characters')
    db_url = os.environ.get('DATABASE_URL')
    if db_url:
        store = await PostgresStore.connect(db_url)
    elif os.environ.get('ALLOW_VOLATILE') == '1':
        store = MemoryStore()
    else:
        raise RuntimeError('DATABASE_URL is required on cloud. Local tests may set ALLOW_VOLATILE=1')
    app.state.store = store
    app.state.connections = {}
    try:
        yield
    finally:
        await store.close()


app = FastAPI(title='Safe Fleet Cloud — Connection Test', lifespan=lifespan, docs_url=None, redoc_url=None)


@app.get('/health')
async def health():
    return {"ok": True, "phase": "read-only telemetry", "movement_enabled": False}


@app.get('/')
async def dashboard():
    return FileResponse(ROOT / 'static' / 'index.html', media_type='text/html',
                        headers={'Cache-Control': 'no-store', 'X-Content-Type-Options': 'nosniff'})


@app.get('/api/turtles')
async def list_turtles(x_admin_key: str | None = Header(default=None)):
    if not valid_token(x_admin_key, os.environ['ADMIN_KEY']):
        raise HTTPException(status_code=401, detail='Invalid admin key')
    rows = await app.state.store.list()
    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            last = datetime.fromisoformat(row['last_seen'])
            recent = (now - last).total_seconds() < HEARTBEAT_AGE_SECONDS
        except (ValueError, KeyError, TypeError):
            recent = False
        # Reconnect never means another server process has the old WebSocket.
        row['online'] = recent and row['id'] in app.state.connections
    return {"turtles": rows, "connected": sum(int(x['online']) for x in rows)}


@app.websocket('/ws/turtle')
async def turtle_socket(ws: WebSocket):
    if not valid_token(ws.headers.get('x-fleet-key'), os.environ['FLEET_KEY']):
        await ws.close(code=1008)
        return
    await ws.accept()
    turtle_id = None
    try:
        raw = await asyncio.wait_for(ws.receive_text(), timeout=15)
        if len(raw) > 4096:
            await ws.close(code=1009)
            return
        hello = json.loads(raw)
        if not isinstance(hello, dict) or hello.get('type') != 'hello':
            await ws.close(code=1008)
            return
        turtle_id = hello.get('id')
        if type(turtle_id) is not int or not 0 <= turtle_id < 2**31:
            await ws.close(code=1008)
            return
        label = str(hello.get('label') or f'Turtle {turtle_id}')[:64]
        old = app.state.connections.get(turtle_id)
        if old:
            await old.close(code=1000)
        app.state.connections[turtle_id] = ws
        await app.state.store.upsert(sanitized_status({}, turtle_id, label))
        await ws.send_json({"type": "welcome", "id": turtle_id, "note": "telemetry only"})
        while True:
            raw = await ws.receive_text()
            if len(raw) > 4096:
                await ws.close(code=1009)
                return
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if isinstance(msg, dict) and msg.get('type') == 'status':
                await app.state.store.upsert(sanitized_status(msg, turtle_id, label))
    except (WebSocketDisconnect, asyncio.TimeoutError, json.JSONDecodeError):
        pass
    finally:
        if turtle_id is not None and app.state.connections.get(turtle_id) is ws:
            del app.state.connections[turtle_id]
