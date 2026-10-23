#!/usr/bin/env python3
"""A lease can be handed to another live owner (0.16.0).

2026-10-22: a daemon leased a run's block, restarted (fleet move), and the
adopted run lost its block when the old daemon exited; the port sweep killed
its emulators mid-scene. The run now takes its block over at startup.
Pure: loads the script as a module; no daemon, no ports.

    python3 test/reown.py
"""
import importlib.machinery, importlib.util, os, pathlib, tempfile, threading

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

b = hm.Broker.__new__(hm.Broker)
b.lock = threading.RLock()
b._save = lambda: None
b.leases = {"L1": {"leaseId": "L1", "kind": "reserved", "block": 11040, "owner_pid": 999999, "owner_start": None}}
me = os.getpid()
check("reown to a live pid", b.reown("L1", me)["ok"] is True)
check("owner is now that pid", b.leases["L1"]["owner_pid"] == me)
check("owner_start recorded", b.leases["L1"]["owner_start"] == hm._proc_start(me))
check("an unknown lease is refused", b.reown("nope", me)["ok"] is False)
check("a dead owner is refused", b.reown("L1", 2**22 + 12345)["ok"] is False)
check("refusal leaves the owner alone", b.leases["L1"]["owner_pid"] == me)
check("the old owner's death no longer reaps it", hm._owner_alive(me, b.leases["L1"]["owner_start"]))

raise SystemExit(1 if failed else 0)
