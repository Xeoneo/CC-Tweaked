# DigitalOcean App Platform — CC:Tweaked Fleet Cloud Starter

**Scope: Phase 1, safe read-only telemetry.** This is a new cloud codebase, not a patch for Safe Fleet v2/v3/v4. It intentionally cannot move or mine with turtles. Start with one turtle; add the protected mining scheduler, automatic return-to-hub, and OTA only after validating connectivity and implementing safety tests.

## Included files

```
app.py                    FastAPI + authenticated WebSocket + PostgreSQL registry
static/index.html         Browser-based monitoring dashboard
requirements.txt          Python dependencies
runtime.txt               Python runtime pin for App Platform
.gitignore                Excludes turtle secrets
turtle/fleet_client.lua   CC:Tweaked read-only telemetry client
 turtle/fleet_config.example.lua   Example WebSocket configuration
 turtle/startup_example.lua        Optional startup launcher
 tests/test_app.py         Local tests
```

## Step 1: Create GitHub repository

1. Extract ZIP onto Mac. Open a new **private GitHub repository** called `minecraft-turtle-fleet`.
2. Upload `app.py`, `requirements.txt`, `runtime.txt`, `.gitignore`, `static/index.html`, `turtle/` and `tests/` **preserving folders**. You can use GitHub's **Add file → Upload files** or `git push` from VS Code.
3. Do not publish `fleet_config.lua` after adding real secrets. Only publish the `.example.lua` file.

## Step 2: Create App Platform app

1. Open https://cloud.digitalocean.com/apps and choose **Create App**.
2. Connect GitHub; select your private repository, main branch, and enable **Autodeploy**.
3. Use a **Web Service**, **one instance**, **Shared Fixed 1 vCPU / 512 MiB** ($5/month). Route at `/`, HTTP port **8080**.
4. Set **Run command**:

   ```
   python -m uvicorn app:app --host 0.0.0.0 --port 8080 --workers 1
   ```

   Do not change `--workers 1`: the initial project maintains active connections in a single process.
5. Region: nearest to your Minecraft server, typically San Francisco if it runs in California.
6. Add a **Development PostgreSQL database** component named `db` (additional $7/month). Under the web service's **Environment Variables**, set:

   `DATABASE_URL` = `${db.DATABASE_URL}` (runtime scope)

   If DigitalOcean already provides `DATABASE_URL` automatically, verify it rather than adding a duplicate.
7. Set two **different, random 32+ character** secrets as encrypted runtime variables:

   - `ADMIN_KEY` = admin dashboard password; never put it in Lua / GitHub.
   - `FLEET_KEY` = turtle authentication; enters only `fleet_config.lua` locally.

   Generate locally on your Mac with `python3 -c 'import secrets; print(secrets.token_urlsafe(32))'` twice.
8. Verify that the final configuration has the `DATABASE_URL` and both keys, then **Create App / Deploy**.

**Cost estimate:** $5/month service + $7/month development DB = **$12/month** before any usage-based extras. The dev database is not backed up automatically. Change to production managed PostgreSQL and set up backups before storing important operational data.

## Step 3: Test cloud website

Open `https://YOUR-APP.ondigitalocean.app/health`. Expected:

```
{"ok":true,"phase":"read-only telemetry","movement_enabled":false}
```

Open `/` and enter `ADMIN_KEY` from App Platform to see the dashboard. If deployment fails, see App Platform **Runtime Logs** for an error. Usually it is a missing `DATABASE_URL`, missing secret, or database initialization failure.

## Step 4: Install a single turtle

1. In Minecraft, use a **Mining Turtle**, not the Advanced Computer. Your existing GPS computers and modem can remain in place.
2. Transfer `turtle/fleet_client.lua` into the turtle CraftOS terminal. Transfer the example configuration and rename it using:

   ```
   move fleet_config.example.lua fleet_config.lua
   edit fleet_config.lua
   ```

   Change the URL to `wss://YOUR-APP.ondigitalocean.app/ws/turtle` and set the actual `FLEET_KEY`. This is a private local file; do not put the admin secret in it.
3. Check the server's CC:Tweaked configuration allows HTTP and WebSockets. Public `wss://` domains are usually permitted by default unless your Minecraft server owner restricts them.
4. Run:

   ```
   fleet_client
   ```

5. Expected: `Connected to cloud`. Refresh the browser dashboard; your turtle ID should show **Online**, with fuel and optional GPS coordinates.
6. After confirming success, **optional**: copy `startup_example.lua` to `startup.lua` (back up an existing startup). This client provides read-only telemetry and **does not operate the miner**.

## Diagnostics

- `/health` works but dashboard says invalid: use `ADMIN_KEY` (not `FLEET_KEY`).
- Dashboard shows no turtles: check turtle terminal, exact `wss://` URL including `/ws/turtle`, enabled HTTP/WebSockets, and correct `FLEET_KEY`.
- Turtle shows `GPS unavailable`: check that four GPS hosts are running in loaded chunks. Telemetry connection can still work.
- App crashes on deploy: confirm PostgreSQL is attached and env var `DATABASE_URL=${db.DATABASE_URL}` works at runtime.
- Turtle reports timeout/disconnect occasionally: it reconnects automatically. App Platform can close idle sockets; the client sends a heartbeat every ~10 seconds.
- Dashboard shows offline after a rollout: existing WebSockets close on deployment; turtles reconnect after about five seconds.
- Your router needs **no port forwarding**, because turtles establish outbound connections to DigitalOcean.

## Local test (optional)

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt pytest httpx
export ALLOW_VOLATILE=1
export ADMIN_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
export FLEET_KEY=$(python3 -c 'import secrets; print(secrets.token_urlsafe(32))')
python -m uvicorn app:app --host 127.0.0.1 --port 8080
```

Do not use volatile storage in production; it loses information whenever the app redeploys. For tests: `python -m pytest -q`.

## What this starter does NOT implement

No mining commands; no autonomous navigation; no safe zones; no ore vein following; no fuel depot control; no item unloading; no software updates. Those need a separate tested turtle agent and cloud scheduler. This starter proves cloud connectivity and registers/monitors turtles; nothing else should be claimed until validated in Minecraft.
