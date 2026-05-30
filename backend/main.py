import time
import os
import json
import threading
from fastapi import FastAPI, HTTPException
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from ai_parser import parse_query, generate_insight
import sdk_runner

app = FastAPI(title="Portaldot Onchain Data Analyst")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"]
)

# ── In-memory cache ────────────────────────────────────────────────────────────
_cache: dict = {}

CACHE_TTL = {
    'get_total_supply':        30,
    'get_top_holders':         20,
    'get_token_concentration': 20,
    'get_transfer_history':    60,
    'get_transfer_volume':     60,
    'get_active_addresses':    60,
    'get_largest_transfers':   60,
    'get_network_stats':       10,
    'get_block_details':       300,
    'get_stale_multisigs':     15,
    'get_richest_multisig':    15,
    'get_multisig_activity':   60,
    'get_remark_logs':         60,
    'get_new_accounts':        60,
    'get_fee_stats':           60,
    'get_block_time':          30,
    'get_account_balance':     10,
    'get_account_nonce':       10,
    'get_account_history':     30,
    'get_account_summary':     20,
}

def _ckey(fn: str, params: dict) -> str:
    return fn + ':' + json.dumps(params, sort_keys=True)

def _cget(key: str, ttl: int):
    if key in _cache:
        val, ts = _cache[key]
        if time.time() - ts < ttl:
            return val, True
        del _cache[key]
    return None, False

def _cset(key: str, val):
    _cache[key] = (val, time.time())


# ── Function map ───────────────────────────────────────────────────────────────
FUNCTION_MAP = {
    "get_top_holders":         sdk_runner.get_top_holders,
    "get_transfer_history":    sdk_runner.get_transfer_history,
    "get_stale_multisigs":     sdk_runner.get_stale_multisigs,
    "get_network_stats":       sdk_runner.get_network_stats,
    "get_account_balance":     sdk_runner.get_account_balance,
    "get_account_history":     sdk_runner.get_account_history,
    "get_total_supply":        sdk_runner.get_total_supply,
    "get_transfer_volume":     sdk_runner.get_transfer_volume,
    "get_active_addresses":    sdk_runner.get_active_addresses,
    "get_token_concentration": sdk_runner.get_token_concentration,
    "get_block_details":       sdk_runner.get_block_details,
    "get_account_summary":     sdk_runner.get_account_summary,
    "get_new_accounts":        sdk_runner.get_new_accounts,
    "get_multisig_activity":   sdk_runner.get_multisig_activity,
    "get_remark_logs":         sdk_runner.get_remark_logs,
    "get_richest_multisig":    sdk_runner.get_richest_multisig,
    "get_fee_stats":           sdk_runner.get_fee_stats,
    "get_block_time":          sdk_runner.get_block_time,
    "get_account_nonce":       sdk_runner.get_account_nonce,
    "get_largest_transfers":   sdk_runner.get_largest_transfers,
}


# ── Cache pre-warming (runs once at startup in background) ─────────────────────
def _prewarm():
    time.sleep(6)  # let the server fully start first
    warm = [
        ('get_total_supply',        {}),
        ('get_top_holders',         {'max_results': 50}),
        ('get_richest_multisig',    {}),
        ('get_stale_multisigs',     {'stale_threshold_blocks': 50}),
        ('get_network_stats',       {'last_n_blocks': 20}),
        ('get_token_concentration', {'top_n': 10}),
    ]
    for fn, params in warm:
        try:
            val = FUNCTION_MAP[fn](**params)
            _cset(_ckey(fn, params), val)
            print(f"[cache] warmed {fn}")
        except Exception as e:
            print(f"[cache] skip {fn}: {e}")

threading.Thread(target=_prewarm, daemon=True).start()


# ── Helpers ────────────────────────────────────────────────────────────────────
def _translate_error(e: Exception) -> str:
    msg = str(e)
    if any(x in msg.lower() for x in ('connectionrefused', 'websocket', 'connect')):
        return "Cannot reach Portaldot node at ws://127.0.0.1:9944 — is the dev node running in WSL?"
    if 'timeout' in msg.lower():
        return "Chain query timed out — the node may be slow. Try a narrower block range."
    if msg.startswith("'") and msg.endswith("'"):
        return f"Unexpected chain data format (missing field {msg})."
    return msg

# Hard cap: block ranges larger than this are silently trimmed
MAX_BLOCK_RANGE = {
    'get_transfer_history':  200,
    'get_transfer_volume':   200,
    'get_active_addresses':  150,
    'get_largest_transfers': 300,
    'get_multisig_activity': 200,
    'get_remark_logs':        80,
    'get_new_accounts':      200,
    'get_fee_stats':         200,
    'get_account_history':   200,
}

def _validate_params(fn_name: str, params: dict) -> dict:
    start = params.get('block_start')
    end   = params.get('block_end')
    if start is not None and start < 1:
        params['block_start'] = 1
    if end is not None and end < 1:
        params['block_end'] = 50
    if start is not None and end is not None and end < start:
        raise ValueError(f"block_end ({end}) must be >= block_start ({start})")
    cap = MAX_BLOCK_RANGE.get(fn_name)
    if cap and start is not None and end is not None and (end - start) > cap:
        params['block_end'] = start + cap
    for key in ('max_results', 'top_n', 'last_n_blocks'):
        if key in params and params[key] <= 0:
            params[key] = 20
    return params


# ── Models ─────────────────────────────────────────────────────────────────────
class Question(BaseModel):
    text: str

class AnalyzeRequest(BaseModel):
    fn_name:  str
    data:     list
    question: str


# ── Routes ─────────────────────────────────────────────────────────────────────
@app.post("/query")
def query(q: Question):
    t0 = time.time()

    try:
        plan = parse_query(q.text)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"AI parsing failed: {str(e)}")

    fn_name = plan.get("function")
    if fn_name not in FUNCTION_MAP:
        raise HTTPException(status_code=400, detail=f"Unknown function: {fn_name!r}. Try rephrasing.")

    try:
        params     = _validate_params(fn_name, plan.get("params", {}))
        cache_key  = _ckey(fn_name, params)
        ttl        = CACHE_TTL.get(fn_name, 20)
        result, from_cache = _cget(cache_key, ttl)
        if not from_cache:
            result = FUNCTION_MAP[fn_name](**params)
            _cset(cache_key, result)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=_translate_error(e))

    try:
        onchain_log = sdk_runner.log_query_onchain(q.text, fn_name)
    except Exception as e:
        onchain_log = {"error": str(e)}

    elapsed_ms = round((time.time() - t0) * 1000)

    return {
        "question":    q.text,
        "plan":        plan,
        "data":        result,
        "onchain_log": onchain_log,
        "elapsed_ms":  elapsed_ms,
        "from_cache":  from_cache,
    }


@app.post("/analyze")
def analyze(req: AnalyzeRequest):
    try:
        insight = generate_insight(req.fn_name, req.data, req.question)
        return {"insight": insight}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


_stats_cache: dict = {}

@app.get("/health")
def health():
    try:
        block = sdk_runner.portaldot.get_block()
        return {"status": "ok", "chain": "connected", "latest_block": block['header']['number']}
    except Exception as e:
        return {"status": "degraded", "chain": "disconnected", "error": str(e)}


@app.get("/stats")
def stats():
    cached, hit = _cget('__stats__', 20)
    if hit:
        return cached
    try:
        block        = sdk_runner.portaldot.get_block()
        total_supply = sdk_runner.portaldot.query('Balances', 'TotalIssuance').value
        result = {
            "latest_block":     block['header']['number'],
            "total_supply_pot": round(total_supply / sdk_runner.POT_DECIMAL, 2),
        }
        _cset('__stats__', result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/blocks/recent")
def blocks_recent(count: int = 4):
    key = f'__blocks_{count}__'
    cached, hit = _cget(key, 6)
    if hit:
        return cached
    try:
        current = sdk_runner.portaldot.get_block()['header']['number']
        result  = []
        for n in range(max(0, current - count + 1), current + 1):
            block = sdk_runner.portaldot.get_block(block_number=n)
            try:
                ts = sdk_runner.portaldot.extensions.get_block_timestamp(n)
            except Exception:
                ts = None
            result.append({"number": n, "extrinsic_count": len(block['extrinsics']), "timestamp_ms": ts})
        out = {"blocks": list(reversed(result)), "latest": current}
        _cset(key, out)
        return out
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/address/{address}")
def address_profile(address: str):
    key = f'__addr_{address}__'
    cached, hit = _cget(key, 15)
    if hit:
        return cached
    try:
        balance = sdk_runner.get_account_balance(address)
        history = sdk_runner.get_account_history(address, block_start=1, block_end=200)
        nonce   = sdk_runner.get_account_nonce(address)
        result  = {"address": address, "balance": balance, "history": history, "nonce": nonce["nonce"]}
        _cset(key, result)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@app.get("/", response_class=HTMLResponse)
def serve_landing():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'landing.html')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()


@app.get("/app", response_class=HTMLResponse)
def serve_app():
    path = os.path.join(os.path.dirname(os.path.abspath(__file__)), '..', 'frontend', 'index.html')
    with open(path, 'r', encoding='utf-8') as f:
        return f.read()
