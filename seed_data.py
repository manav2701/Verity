"""
Run once after starting the local node to populate realistic demo data:
  - 30 transfers across 4 accounts (varied sizes)
  - 2 stale multisig proposals at different ages
  - System remark to mark seed completion
"""
from substrateinterface import SubstrateInterface, Keypair

portaldot = SubstrateInterface(
    url="ws://127.0.0.1:9944",
    ss58_format=42,
    type_registry_preset='substrate-node-template'
)

alice   = Keypair.create_from_uri('//Alice')
bob     = Keypair.create_from_uri('//Bob')
charlie = Keypair.create_from_uri('//Charlie')
dave    = Keypair.create_from_uri('//Dave')
eve     = Keypair.create_from_uri('//Eve')

def submit(call, keypair, label):
    ext = portaldot.create_signed_extrinsic(call=call, keypair=keypair)
    receipt = portaldot.submit_extrinsic(ext, wait_for_inclusion=True)
    status = "ok" if receipt.is_success else f"failed: {receipt.error_message}"
    print(f"  {label} -> {status}")
    return receipt


# ── Transfers: Alice -> Bob (small, frequent) ─────────────────────────────────
print("\n[1/4] Alice -> Bob transfers (10 small)")
for i in range(10):
    call = portaldot.compose_call(
        call_module='Balances',
        call_function='transfer_keep_alive',
        call_params={'dest': bob.ss58_address, 'value': (i + 1) * 10**14}
    )
    submit(call, alice, f"Alice->Bob {i+1}/10 ({i+1} POT)")


# ── Transfers: Alice -> Charlie (medium) ──────────────────────────────────────
print("\n[2/4] Alice -> Charlie transfers (10 medium)")
for i in range(10):
    call = portaldot.compose_call(
        call_module='Balances',
        call_function='transfer_keep_alive',
        call_params={'dest': charlie.ss58_address, 'value': (i + 1) * 5 * 10**14}
    )
    submit(call, alice, f"Alice->Charlie {i+1}/10 ({(i+1)*5} POT)")


# ── Transfers: Bob -> Dave and Eve (larger, fewer) ────────────────────────────
print("\n[3/4] Bob -> Dave/Eve transfers (10 larger)")
for i in range(5):
    call = portaldot.compose_call(
        call_module='Balances',
        call_function='transfer_keep_alive',
        call_params={'dest': dave.ss58_address, 'value': (i + 1) * 20 * 10**14}
    )
    submit(call, bob, f"Bob->Dave {i+1}/5 ({(i+1)*20} POT)")

for i in range(5):
    call = portaldot.compose_call(
        call_module='Balances',
        call_function='transfer_keep_alive',
        call_params={'dest': eve.ss58_address, 'value': (i + 1) * 15 * 10**14}
    )
    submit(call, bob, f"Bob->Eve {i+1}/5 ({(i+1)*15} POT)")


# ── Multisig proposals (2 stale ones) ─────────────────────────────────────────
print("\n[4/4] Seeding stale multisig proposals")

def seed_multisig(initiator, other_signatories, dest, amount_pot, label):
    try:
        inner_call = portaldot.compose_call(
            call_module='Balances',
            call_function='transfer_keep_alive',
            call_params={'dest': dest, 'value': amount_pot * 10**14}
        )
        ms_call = portaldot.compose_call(
            call_module='Multisig',
            call_function='as_multi',
            call_params={
                'threshold':         2,
                'other_signatories': sorted(other_signatories),
                'maybe_timepoint':   None,
                'call':              inner_call.value_serialized,
                'store_call':        True,
                'max_weight':        1000000000,
            }
        )
        submit(ms_call, initiator, label)
    except Exception as e:
        print(f"  {label} skipped: {e}")

# Multisig 1: Alice initiates, Bob+Charlie never approve
seed_multisig(
    alice,
    [bob.ss58_address, charlie.ss58_address],
    dave.ss58_address, 50,
    "Multisig-1 (Alice, needs Bob+Charlie, 50 POT to Dave)"
)

# Multisig 2: Bob initiates, Alice+Dave never approve
seed_multisig(
    bob,
    [alice.ss58_address, dave.ss58_address],
    eve.ss58_address, 100,
    "Multisig-2 (Bob, needs Alice+Dave, 100 POT to Eve)"
)

# ── Completion remark ──────────────────────────────────────────────────────────
print("\nMarking seed completion on-chain...")
remark_call = portaldot.compose_call(
    call_module='System',
    call_function='remark_with_event',
    call_params={'remark': 'portaldot-analyst|seed|demo-data-seeded-v2'}
)
submit(remark_call, alice, "seed remark")

print("\nSeed complete.")
print(f"  Alice:   {alice.ss58_address}")
print(f"  Bob:     {bob.ss58_address}")
print(f"  Charlie: {charlie.ss58_address}")
print(f"  Dave:    {dave.ss58_address}")
print(f"  Eve:     {eve.ss58_address}")
