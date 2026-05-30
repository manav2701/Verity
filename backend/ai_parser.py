import os
import json
import requests
from dotenv import load_dotenv

load_dotenv()
OPENROUTER_KEY = os.getenv("OPENROUTER_API_KEY")

SYSTEM_PROMPT = """
You are an onchain data query planner for the Portaldot blockchain.
The user asks a natural language question. You must respond ONLY with a valid JSON object
specifying which SDK function to call and what parameters to pass.

Available functions and their parameters:

- get_top_holders(max_results: int)
  Use for: "top holders", "richest accounts", "who has the most POT", "wealthiest wallets"

- get_transfer_history(block_start: int, block_end: int)
  Use for: "transfer history", "recent sends", "who sent tokens", "token flows", "transactions"

- get_stale_multisigs(stale_threshold_blocks: int)
  Use for: "stale multisig", "stuck proposals", "pending approvals", "overdue multisig"

- get_network_stats(last_n_blocks: int)
  Use for: "network activity", "transactions per block", "block stats", "how busy is the chain"

- get_account_balance(address: str)
  Use for: "balance of address", "how much does account X have", "wallet balance"

- get_account_history(address: str, block_start: int, block_end: int)
  Use for: "history of account", "what did address X do", "transactions for address"

- get_total_supply()
  Use for: "total supply", "total issuance", "how many POT exist", "circulating supply", "total tokens"

- get_transfer_volume(block_start: int, block_end: int)
  Use for: "transfer volume", "how much POT was moved", "total value transferred", "volume in blocks"

- get_active_addresses(block_start: int, block_end: int)
  Use for: "active addresses", "unique wallets", "how many users", "active accounts", "distinct senders"

- get_token_concentration(top_n: int)
  Use for: "token concentration", "wealth distribution", "top holders percentage", "how concentrated is supply"

- get_block_details(block_number: int)
  Use for: "block details", "what happened in block N", "show block N", "extrinsics in block N"

- get_account_summary(address: str)
  Use for: "account summary", "wallet profile", "full summary for address", "overview of account"

- get_new_accounts(block_start: int, block_end: int)
  Use for: "new accounts", "new wallets created", "account creation events", "who joined"

- get_multisig_activity(block_start: int, block_end: int)
  Use for: "multisig activity", "multisig events", "multisig history", "approvals and executions"

- get_remark_logs(block_start: int, block_end: int)
  Use for: "remark logs", "on-chain remarks", "analyst query log", "what queries were made", "system remarks"

- get_richest_multisig()
  Use for: "richest multisig", "most locked POT", "largest pending multisig", "who has the most locked in multisig"

- get_fee_stats(block_start: int, block_end: int)
  Use for: "fee stats", "how much fees were paid", "total fees", "transaction fees", "gas fees"

- get_block_time(last_n_blocks: int)
  Use for: "block time", "how fast are blocks", "average block time", "block production speed"

- get_account_nonce(address: str)
  Use for: "account nonce", "how many transactions has address sent", "transaction count for address"

- get_largest_transfers(block_start: int, block_end: int, top_n: int)
  Use for: "largest transfers", "biggest transactions", "whale transfers", "top transfers by size"

Defaults if the user does not specify: max_results=50, top_n=10, block_start=1, block_end=100,
stale_threshold_blocks=50, last_n_blocks=20. For get_block_details, default block_number=1.
For get_remark_logs, get_multisig_activity, get_largest_transfers, default block_end=500.

Respond ONLY with a valid JSON object. No markdown. No explanation. No backticks.
Example: {"function": "get_total_supply", "params": {}}
"""


def generate_insight(fn_name: str, data, question: str) -> str:
    if not OPENROUTER_KEY:
        raise ValueError("OPENROUTER_API_KEY not set")

    rows   = data if isinstance(data, list) else [data]
    sample = rows[:15]

    prompt = f"""You are a blockchain data analyst reviewing live data from the Portaldot network.

User question: "{question}"
Query executed: {fn_name}
Total rows: {len(rows)}
Data (first {len(sample)} rows):
{json.dumps(sample, indent=2)}

Write exactly 2-3 sentences of sharp analytical insight. Be specific — use actual numbers from the data. Highlight concentration, anomalies, risks, or patterns. Do not restate the question. Do not say "the data shows" — just state the insight directly."""

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={"Authorization": f"Bearer {OPENROUTER_KEY}", "Content-Type": "application/json"},
        json={
            "model":      "google/gemma-3-27b-it",
            "messages":   [{"role": "user", "content": prompt}],
            "max_tokens": 180,
        },
        timeout=25
    )
    resp.raise_for_status()
    return resp.json()["choices"][0]["message"]["content"].strip()


def parse_query(user_question: str) -> dict:
    if not OPENROUTER_KEY:
        raise ValueError("OPENROUTER_API_KEY not set in .env")

    resp = requests.post(
        "https://openrouter.ai/api/v1/chat/completions",
        headers={
            "Authorization": f"Bearer {OPENROUTER_KEY}",
            "Content-Type": "application/json"
        },
        json={
            "model": "google/gemma-3-27b-it",
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user",   "content": user_question}
            ]
        },
        timeout=30
    )
    resp.raise_for_status()

    raw = resp.json()["choices"][0]["message"]["content"].strip()
    # Strip any accidental markdown fences
    raw = raw.replace("```json", "").replace("```", "").strip()
    return json.loads(raw)
