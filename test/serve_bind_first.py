#!/usr/bin/env python3
"""A broker that loses the port touches nothing (0.17.1).

On the studio (2026-10-23) brokers raced to start after a reboot. Each built
Broker() — load, reap, save the ledger — before binding, so the losers wrote
the ledger beside the winner, corrupted it, and the winner's world sweep
deleted four freshly leased sims. Now the bind comes first.

    python3 test/serve_bind_first.py
"""
import importlib.machinery, importlib.util, os, pathlib, socket, sys, tempfile

HM = pathlib.Path(__file__).resolve().parent.parent / "harbormaster"
def load(state):
    os.environ["FBPORTS_STATE_DIR"] = state
    loader = importlib.machinery.SourceFileLoader("harbormaster", str(HM))
    spec = importlib.util.spec_from_loader("harbormaster", loader)
    m = importlib.util.module_from_spec(spec); loader.exec_module(m); return m

failed = 0
def check(name, ok):
    global failed
    print(("  ok  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1

state = tempfile.mkdtemp()
hm = load(state)
# Hold a port the way a serving broker does, and point this one at it.
held = socket.socket(); held.bind(("127.0.0.1", 0)); held.listen()
hm.BROKER_PORT = held.getsockname()[1]
built = []
hm.Broker = lambda: built.append("Broker()")
hm._touch_managed = lambda: built.append("mark")
code = None
try:
    hm.cmd_serve(managed=True)
except SystemExit as e:
    code = e.code
check("a broker that cannot bind exits non-zero", code == 1)
check("…without building a Broker (no load/reap/save) or writing the mark", built == [])
check("…and leaves no ledger behind", not hm.LEDGER.exists())

# Two writers never share a temp file.
hm2 = load(tempfile.mkdtemp())
br = hm2.Broker.__new__(hm2.Broker); br.leases = {"a": {}}; br.draining = {}
br._save()
left = [p.name for p in hm2.STATE_DIR.iterdir() if ".tmp" in p.name]
check("a save leaves only the ledger (its temp is per-writer and renamed)", left == [] and hm2.LEDGER.exists())
held.close()
print(f"\n{'FAILED' if failed else 'passed'}")
sys.exit(1 if failed else 0)
