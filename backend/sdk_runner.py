import os
import threading
from substrateinterface import SubstrateInterface, Keypair
from substrateinterface.extensions import SubstrateNodeExtension
from dotenv import load_dotenv

_lock = threading.Lock()

load_dotenv()

_NODE_URL = os.getenv('PORTALDOT_WS_URL', 'ws://127.0.0.1:9944')

portaldot = SubstrateInterface(
    url=_NODE_URL,
    ss58_format=42,
    type_registry_preset='substrate-node-template'
)
portaldot.register_extension(SubstrateNodeExtension(max_block_range=500))

POT_DECIMAL = 10**14  # POT token has 14 decimals

# Alice is pre-funded on the local dev node — used to pay gas for query logging
_alice = Keypair.create_from_uri('//Alice')


def log_query_onchain(question: str, fn_name: str) -> dict:
    """
    Submit a System.remark_with_event extrinsic that embeds the NL query and
    resolved function name. This is what makes every analyst query touch the
    chain and pay POT gas, satisfying the Portaldot Native Deployment criterion.
    """
    remark = f"portaldot-analyst|{fn_name}|{question[:200]}"
    call = portaldot.compose_call(
        call_module='System',
        call_function='remark_with_event',
        call_params={'remark': remark}
    )
    extrinsic = portaldot.create_signed_extrinsic(call=call, keypair=_alice)
    receipt = portaldot.submit_extrinsic(extrinsic, wait_for_inclusion=False)
    return {
        'extrinsic_hash': receipt.extrinsic_hash,
        'block_hash':     None,
        'gas_used':       True
    }


def get_top_holders(max_results: int = 50) -> list:
    result = portaldot.query_map('System', 'Account', max_results=max_results)
    holders = []
    for account, info in result:
        free = info.value['data']['free']
        reserved = info.value['data']['reserved']
        holders.append({
            'address':      account.value,
            'free_pot':     round(free / POT_DECIMAL, 4),
            'reserved_pot': round(reserved / POT_DECIMAL, 4),
            'total_pot':    round((free + reserved) / POT_DECIMAL, 4)
        })
    return sorted(holders, key=lambda x: x['total_pot'], reverse=True)


def _transfer_attrs(raw) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        if raw and isinstance(raw[0], dict):
            merged = {}
            for item in raw:
                merged.update(item)
            return merged
        keys = ('from', 'to', 'amount')
        return dict(zip(keys, raw))
    return {}


def get_transfer_history(block_start: int = 1, block_end: int = 100) -> list:
    events = portaldot.extensions.filter_events(
        pallet_name="Balances",
        event_name="Transfer",
        block_start=block_start,
        block_end=block_end
    )
    results = []
    for e in events:
        attr = _transfer_attrs(e.value['attributes'])
        results.append({
            'from':   attr.get('from', attr.get('who', 'unknown')),
            'to':     attr.get('to', 'unknown'),
            'amount': round(attr.get('amount', 0) / POT_DECIMAL, 4),
        })
    return results


def get_stale_multisigs(stale_threshold_blocks: int = 50) -> list:
    current_block = portaldot.get_block()['header']['number']
    pending = portaldot.query_map('Multisig', 'Multisigs', max_results=200)
    stale = []
    for (addr, call_hash), entry in pending:
        created_block = entry.value['when']['height']
        age = current_block - created_block
        if age > stale_threshold_blocks:
            stale.append({
                'multisig':       addr.value,
                'call_hash':      call_hash.value,
                'depositor':      entry.value['depositor'],
                'approvals_done': len(entry.value['approvals']),
                'age_blocks':     age,
                'created_block':  created_block,
                'pot_locked':     round(entry.value['deposit'] / POT_DECIMAL, 4)
            })
    return sorted(stale, key=lambda x: x['age_blocks'], reverse=True)


def get_network_stats(last_n_blocks: int = 20) -> list:
    current_block = portaldot.get_block()['header']['number']
    stats = []
    for n in range(max(0, current_block - last_n_blocks), current_block + 1):
        block = portaldot.get_block(block_number=n)
        try:
            timestamp = portaldot.extensions.get_block_timestamp(n)
        except Exception:
            timestamp = None
        stats.append({
            'block':           n,
            'extrinsic_count': len(block['extrinsics']),
            'timestamp':       timestamp
        })
    return stats


def get_account_balance(address: str) -> dict:
    result = portaldot.query('System', 'Account', [address])
    data = result.value['data']
    return {
        'address':      address,
        'free_pot':     round(data['free'] / POT_DECIMAL, 4),
        'reserved_pot': round(data['reserved'] / POT_DECIMAL, 4),
        'total_pot':    round((data['free'] + data['reserved']) / POT_DECIMAL, 4)
    }


def get_account_history(address: str, block_start: int = 1, block_end: int = 100) -> list:
    events = portaldot.extensions.filter_events(
        pallet_name="Balances",
        event_name="Transfer",
        block_start=block_start,
        block_end=block_end
    )
    relevant = []
    for e in events:
        attr = _transfer_attrs(e.value['attributes'])
        sender = attr.get('from', attr.get('who', ''))
        recipient = attr.get('to', '')
        if address in (sender, recipient):
            relevant.append({
                'from':      sender,
                'to':        recipient,
                'amount':    round(attr.get('amount', 0) / POT_DECIMAL, 4),
                'direction': 'sent' if sender == address else 'received'
            })
    return relevant


# ── helpers ───────────────────────────────────────────────────────────────────

def _norm_attrs(raw, positional_keys: tuple) -> dict:
    if isinstance(raw, dict):
        return raw
    if isinstance(raw, list):
        if raw and isinstance(raw[0], dict) and len(raw[0]) == 1:
            merged = {}
            for item in raw:
                merged.update(item)
            return merged
        return dict(zip(positional_keys, raw))
    return {}


def _decode_remark(raw) -> str:
    if isinstance(raw, bytes):
        return raw.decode('utf-8', errors='replace')
    if isinstance(raw, str) and raw.startswith('0x'):
        try:
            return bytes.fromhex(raw[2:]).decode('utf-8', errors='replace')
        except Exception:
            pass
    return str(raw)


# ── new analytics functions ────────────────────────────────────────────────────

def get_total_supply() -> dict:
    total = portaldot.query('Balances', 'TotalIssuance').value
    return {
        'total_pot':    round(total / POT_DECIMAL, 4),
        'raw_planck':   total
    }


def get_transfer_volume(block_start: int = 1, block_end: int = 100) -> dict:
    events = portaldot.extensions.filter_events(
        pallet_name="Balances", event_name="Transfer",
        block_start=block_start, block_end=block_end
    )
    total, count = 0, 0
    for e in events:
        attr = _transfer_attrs(e.value['attributes'])
        total += attr.get('amount', 0)
        count += 1
    return {
        'block_start':       block_start,
        'block_end':         block_end,
        'transfer_count':    count,
        'total_volume_pot':  round(total / POT_DECIMAL, 4),
        'avg_transfer_pot':  round(total / count / POT_DECIMAL, 4) if count else 0
    }


def get_active_addresses(block_start: int = 1, block_end: int = 100) -> dict:
    events = portaldot.extensions.filter_events(
        pallet_name="Balances", event_name="Transfer",
        block_start=block_start, block_end=block_end
    )
    senders, receivers = set(), set()
    for e in events:
        attr = _transfer_attrs(e.value['attributes'])
        s = attr.get('from', attr.get('who', ''))
        r = attr.get('to', '')
        if s: senders.add(s)
        if r: receivers.add(r)
    return {
        'block_start':            block_start,
        'block_end':              block_end,
        'unique_senders':         len(senders),
        'unique_receivers':       len(receivers),
        'total_active_addresses': len(senders | receivers)
    }


def get_token_concentration(top_n: int = 10) -> list:
    total_supply = portaldot.query('Balances', 'TotalIssuance').value
    accounts = portaldot.query_map('System', 'Account', max_results=200)
    holders = []
    for account, info in accounts:
        bal = info.value['data']['free'] + info.value['data']['reserved']
        if bal > 0:
            holders.append({
                'address':       account.value,
                'total_pot':     round(bal / POT_DECIMAL, 4),
                'pct_of_supply': round(bal / total_supply * 100, 4) if total_supply else 0
            })
    holders.sort(key=lambda x: x['total_pot'], reverse=True)
    return holders[:top_n]


def get_block_details(block_number: int = None) -> list:
    if block_number is None:
        block_number = portaldot.get_block()['header']['number']
    block = portaldot.get_block(block_number=block_number)
    rows = []
    for i, ext in enumerate(block['extrinsics']):
        try:
            v = ext.value if hasattr(ext, 'value') else {}
            call = v.get('call', {}) if isinstance(v, dict) else {}
            signer = str(v.get('address') or 'unsigned') if isinstance(v, dict) else 'unsigned'
            rows.append({
                'index':    i,
                'module':   call.get('call_module', 'unknown'),
                'function': call.get('call_function', 'unknown'),
                'signer':   signer
            })
        except Exception:
            rows.append({'index': i, 'module': 'unknown', 'function': 'unknown', 'signer': 'unknown'})
    return rows


def get_account_summary(address: str) -> dict:
    bal = get_account_balance(address)
    history = get_account_history(address, block_start=1, block_end=500)
    sent     = [h for h in history if h['direction'] == 'sent']
    received = [h for h in history if h['direction'] == 'received']
    return {
        'address':              address,
        'free_pot':             bal['free_pot'],
        'reserved_pot':         bal['reserved_pot'],
        'total_pot':            bal['total_pot'],
        'total_sent_pot':       round(sum(h['amount'] for h in sent), 4),
        'total_received_pot':   round(sum(h['amount'] for h in received), 4),
        'tx_count':             len(history),
        'sent_count':           len(sent),
        'received_count':       len(received)
    }


def get_new_accounts(block_start: int = 1, block_end: int = 200) -> list:
    events = portaldot.extensions.filter_events(
        pallet_name="System", event_name="NewAccount",
        block_start=block_start, block_end=block_end
    )
    result = []
    for e in events:
        attr = e.value['attributes']
        if isinstance(attr, dict):
            account = str(attr.get('account', attr.get('who', str(attr))))
        elif isinstance(attr, list):
            account = str(attr[0]) if attr else 'unknown'
        else:
            account = str(attr)
        result.append({'account': account, 'block_start': block_start, 'block_end': block_end})
    return result


def get_multisig_activity(block_start: int = 1, block_end: int = 100) -> list:
    block_end = min(block_end, block_start + 200)
    results = []
    for event_name in ('NewMultisig', 'MultisigApproval', 'MultisigExecuted', 'MultisigCancelled'):
        try:
            events = portaldot.extensions.filter_events(
                pallet_name="Multisig", event_name=event_name,
                block_start=block_start, block_end=block_end
            )
            for e in events:
                attr = _norm_attrs(e.value['attributes'],
                                   ('approving', 'multisig', 'call_hash'))
                results.append({
                    'event':      event_name,
                    'multisig':   str(attr.get('multisig', attr.get('id', 'unknown'))),
                    'actor':      str(attr.get('approving', attr.get('cancelling', attr.get('who', 'unknown')))),
                    'call_hash':  str(attr.get('call_hash', ''))
                })
        except Exception:
            pass
    return results


def get_remark_logs(block_start: int = 1, block_end: int = 50) -> list:
    current = portaldot.get_block()['header']['number']
    end = min(block_end, current, block_start + 80)
    logs = []
    for n in range(block_start, end + 1):
        try:
            block = portaldot.get_block(block_number=n)
            for ext in block['extrinsics']:
                try:
                    v = ext.value if hasattr(ext, 'value') else {}
                    if not isinstance(v, dict):
                        continue
                    call = v.get('call', {})
                    if (call.get('call_module', '').lower() != 'system' or
                            'remark' not in call.get('call_function', '').lower()):
                        continue
                    remark_raw = ''
                    args = call.get('call_args', [])
                    if isinstance(args, dict):
                        remark_raw = args.get('remark', '')
                    elif isinstance(args, list):
                        for arg in args:
                            if isinstance(arg, dict) and arg.get('name') == 'remark':
                                remark_raw = arg.get('value', '')
                                break
                    logs.append({
                        'block':  n,
                        'signer': str(v.get('address') or 'unsigned'),
                        'remark': _decode_remark(remark_raw)
                    })
                except Exception:
                    pass
        except Exception:
            pass
    return logs


def get_richest_multisig() -> list:
    pending = portaldot.query_map('Multisig', 'Multisigs', max_results=200)
    result = []
    for (addr, call_hash), entry in pending:
        result.append({
            'multisig':       addr.value,
            'call_hash':      call_hash.value,
            'depositor':      entry.value['depositor'],
            'approvals_done': len(entry.value['approvals']),
            'pot_locked':     round(entry.value['deposit'] / POT_DECIMAL, 4)
        })
    return sorted(result, key=lambda x: x['pot_locked'], reverse=True)


def get_fee_stats(block_start: int = 1, block_end: int = 100) -> dict:
    try:
        events = portaldot.extensions.filter_events(
            pallet_name="TransactionPayment", event_name="TransactionFeePaid",
            block_start=block_start, block_end=block_end
        )
        total_fee, count = 0, 0
        for e in events:
            attr = _norm_attrs(e.value['attributes'], ('who', 'actual_fee', 'tip'))
            total_fee += attr.get('actual_fee', 0)
            count += 1
        return {
            'block_start':    block_start,
            'block_end':      block_end,
            'tx_count':       count,
            'total_fees_pot': round(total_fee / POT_DECIMAL, 6),
            'avg_fee_pot':    round(total_fee / count / POT_DECIMAL, 6) if count else 0,
        }
    except Exception:
        return {'block_start': block_start, 'block_end': block_end,
                'tx_count': 0, 'total_fees_pot': 0, 'avg_fee_pot': 0,
                'note': 'TransactionPayment events unavailable in this runtime'}


def get_block_time(last_n_blocks: int = 20) -> dict:
    current = portaldot.get_block()['header']['number']
    diffs, prev_ts = [], None
    for n in range(max(1, current - last_n_blocks), current + 1):
        try:
            ts = portaldot.extensions.get_block_timestamp(n)
            if ts and prev_ts and ts > prev_ts:
                diffs.append(ts - prev_ts)
            prev_ts = ts
        except Exception:
            pass
    if not diffs:
        return {'avg_block_time_s': 'N/A', 'min_block_time_s': 'N/A',
                'max_block_time_s': 'N/A', 'sample_size': 0}
    return {
        'avg_block_time_s': round(sum(diffs) / len(diffs) / 1000, 2),
        'min_block_time_s': round(min(diffs) / 1000, 2),
        'max_block_time_s': round(max(diffs) / 1000, 2),
        'sample_size':      len(diffs),
    }


def get_account_nonce(address: str) -> dict:
    result = portaldot.query('System', 'Account', [address])
    return {
        'address':   address,
        'nonce':     result.value['nonce'],
        'consumers': result.value.get('consumers', 0),
        'providers': result.value.get('providers', 0),
    }


def get_largest_transfers(block_start: int = 1, block_end: int = 500, top_n: int = 10) -> list:
    events = portaldot.extensions.filter_events(
        pallet_name="Balances", event_name="Transfer",
        block_start=block_start, block_end=block_end
    )
    transfers = []
    for e in events:
        attr = _transfer_attrs(e.value['attributes'])
        transfers.append({
            'from':       attr.get('from', attr.get('who', 'unknown')),
            'to':         attr.get('to', 'unknown'),
            'amount_pot': round(attr.get('amount', 0) / POT_DECIMAL, 4),
        })
    transfers.sort(key=lambda x: x['amount_pot'], reverse=True)
    return transfers[:top_n]
