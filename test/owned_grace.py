#!/usr/bin/env python3
"""A reserved block with a live owner survives a suite restart (0.15.1).

2026-10-22: a resumed story's emulator suite was down for over 45s while it
re-imported its checkpoint; the broker reaped the block under its live owner,
re-leased it, and the next caller's port sweep killed the run's emulators.
Pure: loads the script as a module; no daemon, no ports.

    python3 test/owned_grace.py
"""
import importlib.machinery, importlib.util, os, pathlib, tempfile

HM = pathlib.Path(__file__).resolve().parent.parent / "harbormaster"
os.environ["FBPORTS_STATE_DIR"] = tempfile.mkdtemp()
loader = importlib.machinery.SourceFileLoader("harbormaster", str(HM))
spec = importlib.util.spec_from_loader("harbormaster", loader)
hm = importlib.util.module_from_spec(spec); loader.exec_module(hm)

failed = 0
def check(name, ok):
    global failed
    print(("  ok  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1

hm._port_open = lambda port, host="127.0.0.1": False   # the suite is down
hm._owner_alive = lambda pid, start: True
b = hm.Broker.__new__(hm.Broker)
def lease(**kw):
    return {"leaseId": "x", "kind": "reserved", "block": 11000, "expires": None,
            "seen_active": True, "down_since": 1000, **kw}

owned = lease(owner_pid=4242)
check("owned, down 60s: kept", b._dead_reason(owned, 1060) is None)
check("owned, down 10 min: kept", b._dead_reason(owned, 1600) is None)
check("owned, down past the owned grace: reaped",
      b._dead_reason(owned, 1000 + hm.OWNED_RECLAIM_GRACE) == "reserved block down past grace")
check("no owner, down 45s: reaped as before",
      b._dead_reason(lease(), 1000 + hm.RECLAIM_GRACE) == "reserved block down past grace")
hm._owner_alive = lambda pid, start: False
check("owner gone: reaped at once", (b._dead_reason(lease(owner_pid=4242), 1001) or "").startswith("owner pid 4242 gone"))

raise SystemExit(1 if failed else 0)
