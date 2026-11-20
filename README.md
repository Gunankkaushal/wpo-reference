# wpo-reference

A stand-in **Workforce Optimization (WPO)** product for NaviStorm demos. It has five agents on LangGraph, and they reach six stubbed enterprise systems only through MCP.

> This is not a WPO application. Every system is a stub with canned data. It exists so NaviStorm has a realistic agent graph to discover, inject faults into and score.

```
                 ┌──────────── wpo_nightly_roster (LangGraph supervisor) ────────────┐
                 │ supervisor → forecast_demand → optimize_roster → compliance ─┬─pass─→ writeback → END
                 │                                     ▲                        │
                 │                                     └──────── fail ──────────┘ (max_iter 4, then give_up)
                 └───────────────────────────────────────────────────────────────────┘
                 ┌──── wpo_manager_copilot (separate graph, business hours) ────┐
                 │ business_hours_gate → load_roster → answer                   │
                 └──────────────────────────────────────────────────────────────┘
                                 │  every call is an MCP tool call
                                 ▼
   MCP :9101 sap   :9102 workday   :9103 mes   :9104 lms   :9105 cuopt   :9106 teams   :9107 policy   :9108 roster
                                 │  HTTP
                                 ▼
   stub-sap :8101   stub-workday :8102   stub-mes :8103   stub-lms :8104   stub-cuopt :8105   stub-teams :8106
```

## Run it

### Docker (one container for all systems)

```bash
docker compose up -d --build wpo-systems wpo-ui          # 6 stubs + 8 MCP servers + WPO console on :8000
docker compose run --rm wpo-agents nightly               # nightly roster journey
docker compose run --rm wpo-agents ask "Who is on L1 early?" --site SITE-01 --ignore-hours
```

### Without Docker

```bash
python -m venv .venv && .venv/Scripts/pip install -r requirements.txt   # bin/ on macOS/Linux
python run_systems.py                     # terminal 1
python -m wpo_ui                          # terminal 3: WPO console at http://127.0.0.1:8000
python -m wpo_agents nightly              # terminal 2
python -m wpo_agents ask "Who is on L1 early?" --site SITE-01 --ignore-hours
python -m wpo_agents graph                # both graphs as Mermaid
python -m wpo_agents discover             # rebuild the NaviStorm topology from traces + MCP manifests
```

### WPO console (front end)

http://localhost:8000 is the WPO product's own web front end ([wpo_ui/](wpo_ui/)). It drives the same LangGraph agents as the CLI, so every system call is still an agent's MCP tool call on the same edges E01–E18, with the same spans. It has these tabs:

- **Overview**: the 5 agents, their 18 edges, and system health
- **Nightly roster run**: run the journey and watch each node live, including forecast retry warnings
- **Published roster**: the latest approved roster, per site
- **Manager Copilot**: chat with the copilot (business-hours gate can be bypassed for demos)
- **Systems & calls**: stub and MCP liveness, plus call counts per endpoint (`FAULTED` rows show injected errors)
- **Agent graph**: both LangGraph graphs rendered as Mermaid

The console only reads stub `/health` and `/_stats` as demo aids. It never calls a system's business endpoints.

A clean nightly run takes about 4 s locally and looks like this:

```
 - supervisor: run-20261120-115949 opened for plan date 2026-11-20
 - forecast_demand: 14 sites, 102 slots, 0 retries
 - optimize_roster: iteration 1, 96 assignments, 6 unfilled, excluded none
 - compliance: fail (2 violation(s): W-0101 max_weekly_hours, W-0605 max_weekly_hours)
 - optimize_roster: iteration 2, 95 assignments, 7 unfilled, excluded ['W-0101', 'W-0605']
 - compliance: pass
 - writeback: published 14 sites, Teams notified
```

Compliance always fails the first candidate. Two workers in the canned data are near the 48 h cap, and the solver doesn't know that rule. This exercises the `fail → optimizer` edge on every run.

With no `AZURE_OPENAI_*` set, the LLM calls (E04, E18) use a deterministic offline responder. The spans are still emitted.

## The stubs

| Stub | Stands for | Endpoint | Returns |
|---|---|---|---|
| stub-sap | SAP S/4 | `GET /production_plan` | 14 sites, units per line per shift |
| | | `POST /shift_confirm` | `{"status":"ok"}` |
| stub-workday | Workday | `GET /absences` | 13 approved absences |
| | | `GET /workers` | 168 workers (12 per site) |
| | | `POST /schedules` | `{"status":"ok"}` |
| stub-mes | MES | `GET /line_availability` | 28 lines, 3 with downtime |
| stub-lms | Learning system | `GET /training_currency` | per worker per line, 5 expired |
| stub-cuopt | NVIDIA cuOpt | `POST /solve` | `{"status":"OK","roster":{…}}` |
| stub-teams | Microsoft Teams | `POST /notify` | `{"status":"ok"}` |

Canned data lives in [stubs/canned.py](stubs/canned.py). The cuOpt stub runs a trivial greedy fill so the roster isn't empty.

Every stub also has demo aids under `/_`. They are not part of the system being stood in for:

| | |
|---|---|
| `GET /_stats` | call counts per endpoint, including `FAULTED …` counts |
| `GET /_writes` | payloads received on write endpoints |
| `POST /_fault` | local fault hook for rehearsing without NaviStorm |
| `DELETE /_fault`, `POST /_reset` | clear |

## MCP servers

Agents never call a stub's HTTP endpoint. No module in `wpo_agents/` imports an HTTP client. Each system has one MCP server (streamable HTTP, stateless, at `/mcp`).

| Server | Tool | Hints |
|---|---|---|
| sap | `production_plan` | readOnly |
| | `shift_confirm` | **destructiveHint: true** |
| workday | `absences`, `workers` | readOnly |
| | `schedules` | **destructiveHint: true** |
| mes | `line_availability` | readOnly |
| lms | `training_currency` | readOnly |
| cuopt | `solve` | readOnly, not idempotent |
| teams | `notify` | **destructiveHint: true** |
| policy | `rules` | readOnly (ruleset held in the server) |
| roster | `store` (`action="put"` writes, `action="latest"` reads) | **destructiveHint: true** |

That is 11 tools in total, matching the topology screen. Every tool's `_meta["wpo/backend"]` says what sits behind its server: `external_system` for the 6 systems, `internal_service` for policy and roster. Discovery can then count systems from the manifest alone.

Upstream status codes, `Retry-After` and timeouts pass through to the agent as structured tool errors.

## Agents and node config

| Node | Calls (edge) | Config | Where |
|---|---|---|---|
| `forecast_demand` | sap.production_plan (E01), mes.line_availability (E02), workday.absences ×14 (E03), Azure OpenAI ×14 (E04) | **Retry unbounded, fixed 0.5 s, ignores Retry-After** | [nodes/forecast_demand.py](wpo_agents/nodes/forecast_demand.py) |
| `optimize_roster` | workday.workers (E07), lms.training_currency (E08), cuopt.solve (E09), roster.store (E10) | Retry 2 (`max_attempts=3`), max_iter 4 | [nodes/optimize_roster.py](wpo_agents/nodes/optimize_roster.py) |
| `compliance` | policy.rules (E11), lms.training_currency (E12), roster.store (E13) | No retry. pass → writeback, fail → optimizer | [nodes/compliance.py](wpo_agents/nodes/compliance.py) |
| `writeback` | workday.schedules ×14 (E14), sap.shift_confirm ×14 (E15), teams.notify (E16) | Write path. Retries on `ToolTimeout` only | [nodes/writeback.py](wpo_agents/nodes/writeback.py) |
| `manager_copilot` | roster.store action=latest (E17), Azure OpenAI (E18) | Separate graph, Mon–Fri 08:00–18:00 | [manager_copilot.py](wpo_agents/manager_copilot.py) |

E05/E06 (forecast-queue) are a graph-state hand-off here, not a real queue.

## The deliberate defect

`forecast_demand` retries every failed call forever, after a fixed delay with no jitter, and ignores `Retry-After`. It is fenced with a **DO NOT FIX** comment. It is the weakness the first demo is built on (experiment `exp-0117`: Workday 429 on E03).

Rehearse it without NaviStorm:

```bash
curl -X POST localhost:8102/_reset
curl -X POST localhost:8102/_fault -H 'content-type: application/json' \
  -d '{"status":429,"rate":0.3,"duration_s":240,"retry_after":5,"paths":["/absences"]}'
python -m wpo_agents nightly
curl localhost:8102/_stats        # GET /absences far above 14 = self-inflicted load
```

The log shows the defect directly:

```
WARNING wpo.forecast  workday.absences[SITE-01] attempt 1 failed (workday.absences: HTTP 429); Retry-After=5 ignored; retrying in 0.5s
```

## Behaviours the other findings rely on

These aren't planted. They are how the code is naturally written, and they match the findings on the wireframe's Findings screen:

- **Optimizer waits for all 14 sites.** Forecast processes sites one by one, and stage 2 starts only when every site is done.
- **Copilot serves a stale roster unlabelled.** It answers from the latest approved roster in the store and never says when that roster was generated. `roster.store` is seeded with yesterday's roster, so after a failed night the Copilot answers from yesterday's.
- **Writeback duplicate writes.** A timeout re-runs the whole node with no idempotency key, so earlier sites are re-published.

## Connecting NaviStorm

- **MCP proxy:** set `MCP_<SERVER>_URL` (e.g. `MCP_WORKDAY_URL`) to the proxy. No code change.
- **Model gateway:** point `AZURE_OPENAI_ENDPOINT` at the gateway.
- **Discovery:** set `OTEL_EXPORTER_OTLP_ENDPOINT`. Spans use OTel GenAI conventions (`gen_ai.operation.name`, `gen_ai.tool.name`, `gen_ai.agent.name`) and carry `wpo.edge_id`, so they match E01–E18.
- **What discovery sees:**
  - Traces mark the one orchestrator with `gen_ai.operation.name=invoke_workflow`, which has no `gen_ai.agent.name`.
  - Each agent has an `invoke_agent` span. Manager Copilot's root span is `invoke_agent`, so it counts as an agent, not a second orchestrator.
  - Tool calls are `execute_tool` spans and model calls are `chat` spans.
  - E05/E06 are `messaging.*` producer and consumer spans on `forecast-queue`.
  - MCP manifests add tool names, read/write hints and the system behind each server.
- **Check it:** `python -m wpo_agents discover` (or `docker compose run --rm wpo-agents discover`). It builds the topology from those two sources only, with no config file, and writes it to `data/discovered_topology.json`. It records `classified_by` (`otel_trace`, `mcp_manifest` or both) on every node and edge, and checks the totals: 1 orchestrator, 5 agents, 11 MCP tools, 6 systems, 18 edges. It runs the nightly journey once, which publishes to the stubs. `--no-run` reads the manifests only.
- **Declared topology:** [topology.yaml](topology.yaml) has the same 5 agents, 6 systems and 18 edges for import.

See [.env.example](.env.example) for every setting.
