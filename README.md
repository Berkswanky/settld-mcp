# Settld MCP server

Custom tools for the Settld tenancy agent on AgenticOrg: voice (Gnani-style), logistics (Delhivery-style),
field service (Urban Company mock), mandate guard, evidence ledger, purpose/evidence gate and sandbox payments.
All rails are mock/sandbox with scripted demo scenarios. State is in memory and resets on restart.

## Deploy on Render (free, about 10 minutes)

1. Create a new **public** GitHub repository, e.g. `settld-mcp`.
2. Upload these files to it: `server.py`, `requirements.txt`, `render.yaml`, `.gitignore`, `README.md`
   (GitHub: "Add file" -> "Upload files" -> drag them in -> "Commit changes").
3. Go to https://render.com, sign up with GitHub.
4. Click **New -> Web Service**, pick the `settld-mcp` repository.
5. Settings (Render usually fills these from render.yaml):
   - Runtime: **Python**
   - Build command: `pip install -r requirements.txt`
   - Start command: `python server.py`
   - Instance type: **Free**
6. Click **Deploy**. Wait until the log shows `Uvicorn running on http://0.0.0.0:...`.
7. Your MCP Server URL is the Render URL plus `/mcp`, for example:
   `https://settld-mcp.onrender.com/mcp`

Free Render services sleep after ~15 minutes of no traffic and take ~1 minute to wake up.
Open the URL in a browser a minute before registering or demoing to wake it.

## Register in AgenticOrg

Dashboard -> Connectors -> Add Connector:
- Connector Name: `settld_tools`
- Tick **MCP**
- MCP Server URL: `https://<your-service>.onrender.com/mcp`
- Category: `ops`   Auth Type: `none`   Rate limit: 100
- Click **Register**. It should discover 27 tools.

## Demo scenarios built in

| Property / job | What happens |
| --- | --- |
| P1 Skyline Heights | Happy path: broker unknown -> owner verified_with_risk -> society verified, rent 48,000 |
| P2 ABC Residency | Contradiction: broker "should be fine", owner "no" (contested), society "no" (failed, dropped) |
| P3 Green Park Villa | Owner insists on 53,000 > 50,000 ceiling -> HUMAN_REQUIRED |
| P4 Lakeview Towers | Owner and society never answer -> chase policy -> escalate to renter |
| Repair: PRO-RAVI | Quote 2,400 (auto-allowed); first fix fails, payment blocked; rework passes, then pays |
| Repair: PRO-QFIX | Quote 5,800 > 3,000 limit -> HUMAN_REQUIRED |
| Logistics | First pickup NDR -> PICKUP_RESCHEDULE -> IN_TRANSIT -> DELIVERED with POD |

Call `reset_demo` before each demo run.

## Run locally

    pip install -r requirements.txt
    python server.py          # serves http://localhost:8000/mcp
