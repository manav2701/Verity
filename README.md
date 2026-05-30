# Portaldot Onchain Analyst

An AI-powered natural language interface for querying live Portaldot blockchain data.
Type a question in plain English — Gemma AI routes it to the correct SDK query and returns
structured results instantly, with every query logged on-chain as a signed extrinsic.

---

## Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│  Browser  (frontend/index.html)                                 │
│  ┌──────────────┐  ┌──────────────┐  ┌─────────────────────┐   │
│  │ NL Input     │  │ Dashboard    │  │ Live Block Feed     │   │
│  │ Query chips  │  │ Stats panel  │  │ (polls /blocks)     │   │
│  │ Result table │  │ (polls /stats│  │                     │   │
│  │ Charts (CJS) │  │ every 15s)   │  │                     │   │
│  └──────┬───────┘  └──────────────┘  └─────────────────────┘   │
└─────────┼───────────────────────────────────────────────────────┘
          │  POST /query
          ▼
┌─────────────────────────────────────────────────────────────────┐
│  FastAPI Backend  (backend/main.py)                             │
│  ┌──────────────┐    ┌──────────────┐    ┌──────────────────┐  │
│  │ ai_parser.py │    │ sdk_runner.py│    │ Endpoints:       │  │
│  │              │    │              │    │ POST /query      │  │
│  │ OpenRouter   │───▶│ 20 query     │    │ GET  /health     │  │
│  │ Gemma 27B    │    │ functions    │    │ GET  /stats      │  │
│  │              │    │              │    │ GET  /blocks/... │  │
│  │ NL → fn name │    │ SubstrateIF  │    │ GET  /address/.. │  │
│  └──────────────┘    └──────┬───────┘    └──────────────────┘  │
└─────────────────────────────┼───────────────────────────────────┘
                              │  WebSocket  ws://127.0.0.1:9944
                              ▼
┌─────────────────────────────────────────────────────────────────┐
│  Portaldot Dev Node  (WSL / Ubuntu 24.04)                       │
│                                                                 │
│  substrate-node-template  --dev  --alice                        │
│  Block time: ~6s    Token: POT (14 decimals)                    │
│  Pre-funded: Alice, Bob, Charlie, Dave, Eve                     │
└─────────────────────────────────────────────────────────────────┘
```

---

## Features

- **20 query types** — balances, transfers, multisigs, network stats, fee data, block details and more
- **AI routing** — Gemma 27B (via OpenRouter) maps any natural language question to the correct function
- **On-chain logging** — every query submits a `System.remark_with_event` extrinsic signed by Alice, paying real POT gas (satisfies Portaldot Native Deployment criterion)
- **Live dashboard** — block number, total supply, holder count, auto-refreshing every 15s
- **Live block feed** — sidebar showing new blocks as they arrive
- **Charts** — Chart.js visualisations for network activity, token distribution, transfer history, multisig age
- **Address profiles** — click any address in a result table to open a balance + history modal with a mini chart
- **Export** — download any result as CSV or JSON

---

## Setup

### Prerequisites

- Windows with WSL2 (Ubuntu 24.04)
- Python 3.12 (`winget install Python.Python.3.12`)
- OpenRouter API key (free tier works)

### 1 — Start the dev node in WSL

```bash
wsl
cd ~
./portaldot-testnet-ubuntu --dev --alice
```

Leave this terminal running. The node produces a block every ~6 seconds.

### 2 — Create the Python virtual environment (Windows)

```powershell
cd C:\Users\<you>\OneDrive\Desktop\portaldot
py -3.12 -m venv venv
venv\Scripts\pip install -r backend\requirements.txt
```

### 3 — Configure API key

Copy `.env.example` to `.env` and fill in your OpenRouter key:

```
OPENROUTER_API_KEY=sk-or-v1-...
```

### 4 — Seed demo data (first time only)

```powershell
venv\Scripts\python seed_data.py
```

Seeds 30 transfers across 5 accounts and 2 stale multisig proposals.

### 5 — Start the backend

```powershell
cd backend
..\venv\Scripts\uvicorn.exe main:app --reload --port 8000
```

### 6 — Open the frontend

Open `frontend/index.html` in Chrome. The dashboard will show live chain stats immediately.

---

## Query examples

| Question | Function called |
|---|---|
| Top 20 POT holders | `get_top_holders(max_results=20)` |
| Transfer volume blocks 1 to 100 | `get_transfer_volume(block_start=1, block_end=100)` |
| Show stale multisig approvals | `get_stale_multisigs(stale_threshold_blocks=50)` |
| Average block time last 20 blocks | `get_block_time(last_n_blocks=20)` |
| Who has the most locked POT in pending multisigs | `get_richest_multisig()` |
| Largest transfers blocks 1 to 500 | `get_largest_transfers(block_start=1, block_end=500)` |
| Fee stats blocks 1 to 100 | `get_fee_stats(block_start=1, block_end=100)` |
| Show remark logs blocks 1 to 500 | `get_remark_logs(block_start=1, block_end=500)` |
| Total token supply | `get_total_supply()` |
| Block details block 5 | `get_block_details(block_number=5)` |

---

## Project structure

```
portaldot/
├── backend/
│   ├── main.py          # FastAPI app, all endpoints
│   ├── sdk_runner.py    # 20 chain query functions + on-chain logger
│   ├── ai_parser.py     # OpenRouter / Gemma NL → function router
│   └── requirements.txt
├── frontend/
│   └── index.html       # Single-file UI (vanilla JS + Chart.js CDN)
├── seed_data.py         # One-time demo data seeder
├── .env                 # API keys (not committed)
├── .env.example
└── README.md
```

---

## Tech stack

| Layer | Technology |
|---|---|
| Blockchain | Portaldot (Substrate-based, V13 metadata) |
| Chain SDK | substrate-interface (Python) |
| AI model | Gemma 3 27B via OpenRouter |
| Backend | FastAPI + Uvicorn |
| Frontend | Vanilla HTML/JS + Chart.js |
| Gas token | POT (14 decimal places) |

---

## Pointing at a real network

Change one line in `backend/sdk_runner.py`:

```python
# local dev node
url="ws://127.0.0.1:9944"

# Portaldot mainnet / testnet
url="wss://rpc.portaldot.io"
```

All 20 query functions and the AI routing work identically on mainnet.
The `seed_data.py` script is not needed — organic chain data replaces it.
