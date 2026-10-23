#!/usr/bin/env python3
"""With a managed service installed, a client never starts its own broker (0.18.0).

The studio (2026-10-23): after a reboot the managed broker was down long enough
for its freshness marker to go stale, so a client started a plain `serve` that
held port 4999 for good, and launchd's broker crash-looped behind it.
`serve --managed --unit <path>` declares the service; while the unit file
exists, clients wait for it and then fail loudly instead. Pure: no daemon.

    python3 test/managed_unit.py
"""
import importlib.machinery, importlib.util, os, pathlib, sys, tempfile, time

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
hm.STATE_DIR.mkdir(parents=True, exist_ok=True)
unit = pathlib.Path(tempfile.mkdtemp()) / "com.example.harbormaster.plist"
unit.write_text("<plist/>")
hm._declare_managed(str(unit))
check("a declared, installed unit is the managed service", hm._managed_unit() == str(unit))

calls = []
hm._spawn_daemon = lambda: calls.append("spawn")
hm._call = lambda *a, **k: calls.append(("call",) + a)
hm.time.sleep = lambda s: None

# Service installed, marker STALE (its broker is down), nothing serving:
# wait, then fail — never spawn.
hm._daemon_version = lambda: None
hm._up = lambda: False
err = None
try:
    hm._ensure()
except RuntimeError as e:
    err = str(e)
check("installed but down: no stray broker is started", calls == [])
check("…and the client fails naming the unit", err is not None and str(unit) in err)

# Service installed, an OLDER unmanaged broker serving: not the client's to
# replace (that would be one more stray).
hm._daemon_version = lambda: "0.1.0"
hm._up = lambda: True
hm._ensure()
check("installed: an older stray broker is left for the installer to evict", calls == [])

# Service uninstalled (unit deleted): the old behaviour returns.
unit.unlink()
check("a deleted unit no longer counts", hm._managed_unit() is None)
calls.clear()
hm._daemon_version = lambda: None
ups = iter([False, True])
hm._up = lambda: next(ups, True)
hm._ensure()
check("with no service, a client starts one as before", calls == ["spawn"])

print(f"\n{'FAILED' if failed else 'passed'}")
sys.exit(1 if failed else 0)
