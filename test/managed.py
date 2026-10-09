#!/usr/bin/env python3
"""A managed broker is never replaced or shadowed by a client (0.11.0).

On simon-linux-1 (2026-10-09) the shared broker was started by an SSB job's
checkout, and before that a CI job whose orphan cleanup killed it — and every
emulator it ran for other jobs — mid-suite. Under `serve --managed` a service
manager owns it. Pure: loads the script as a module; no daemon, no ports.

    python3 test/managed.py
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
check("no marker: not managed", hm._managed_recent() is False)
hm.STATE_DIR.mkdir(parents=True, exist_ok=True)
hm._touch_managed()
check("a fresh marker: managed", hm._managed_recent() is True)

calls = []
hm._spawn_daemon = lambda: calls.append("spawn")
hm._call = lambda *a, **k: calls.append(("call",) + a)
# An OLDER broker that is managed: left alone — no /shutdown, no spawn.
hm._daemon_version = lambda: "0.9.1"
hm._up = lambda: True
hm._ensure()
check("an older managed broker is not replaced", calls == [])

# Down while managed: wait for the service to bring it back, never spawn.
ups = iter([False, False, True])
hm._daemon_version = lambda: None
hm._up = lambda: next(ups, True)
hm.time.sleep = lambda s: None
hm._ensure()
check("a managed broker that is restarting is waited for, not shadowed", calls == [])

# A stale marker: the service is gone — spawn as before.
old = time.time() - hm.MANAGED_FRESH_S - 10
os.utime(hm.MANAGED_MARK, (old, old))
check("a stale marker: not managed", hm._managed_recent() is False)
state_up = iter([False, True])
hm._up = lambda: next(state_up, True)
hm._ensure()
check("with no service, a client starts one as before", calls == ["spawn"])

print(f"\n{'FAILED' if failed else 'passed'}")
sys.exit(1 if failed else 0)
