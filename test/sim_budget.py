#!/usr/bin/env python3
"""The box's simulator budget holds for every caller (0.22.0).

2026-11-06, the Mac Studio: 6-7 simulators beside their emulator stacks, CPU at
75-98% all day, swap 98% full, simctl install/addmedia stalling for minutes.
SSB's scheduler had a budget; CI's Detox suites and anything run by hand had
none. harbormaster makes every private simulator, so the gate lives here.
Pure: loads the script as a module; no daemon, no simctl.

    python3 test/sim_budget.py
"""
import importlib.machinery, importlib.util, io, json, os, pathlib, sys, tempfile, contextlib

HM = pathlib.Path(__file__).resolve().parent.parent / "harbormaster"
os.environ["FBPORTS_STATE_DIR"] = tempfile.mkdtemp()
os.environ.pop("FBPORTS_MAX_SIMS", None)
loader = importlib.machinery.SourceFileLoader("harbormaster", str(HM))
spec = importlib.util.spec_from_loader("harbormaster", loader)
hm = importlib.util.module_from_spec(spec); loader.exec_module(hm)

failed = 0
def check(name, ok):
    global failed
    print(("  ok  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1

A, B, C, D = ("AAAAAAAA-0000-0000-0000-000000000001", "BBBBBBBB-0000-0000-0000-000000000002",
              "CCCCCCCC-0000-0000-0000-000000000003", "DDDDDDDD-0000-0000-0000-000000000004")

# -- the budget: env, then the file; anything else is no gate
check("no file, no env: no gate", hm.sim_budget() is None)
hm.SIM_BUDGET_FILE.write_text(json.dumps({"max": 4}))
check("the file's max", hm.sim_budget() == 4)
os.environ["FBPORTS_MAX_SIMS"] = "2"
check("FBPORTS_MAX_SIMS wins over the file", hm.sim_budget() == 2)
os.environ["FBPORTS_MAX_SIMS"] = "junk"
check("an unreadable env is no gate, never 'full'", hm.sim_budget() is None)
os.environ.pop("FBPORTS_MAX_SIMS")
for bad in ('{"max": 0}', '{"max": -1}', '{"max": "4"}', '{"max": true}', 'not json', '{}'):
    hm.SIM_BUDGET_FILE.write_text(bad)
    check(f"{bad!r} is no gate", hm.sim_budget() is None)

# -- what counts
check("booted devices count; a leased one that is shut down does not", hm.sims_in_use({A, B}, {B, C}, set(), 0) == 2)
check("a booted device no lease holds counts (a leftover, CI's own)", hm.sims_in_use({A}, set(), set(), 0) == 1)
check("a lease still making its device counts", hm.sims_in_use(set(), set(), set(), 2) == 2)
check("…but not twice once its device has booted",
      hm.sims_in_use({A, D}, {A}, {A, D}, 1) == 2)
check("case never splits a device", hm.sims_in_use({A.lower()}, {A}, {A}, 1) == 2)

# -- the gate, under the broker's lock
b = hm.Broker.__new__(hm.Broker)
b.lock, b.leases, b.draining = hm.threading.RLock(), {}, {}
hm._authored_sims = lambda: set()
hm.SIM_BUDGET_FILE.write_text(json.dumps({"max": 3}))
b.leases = {"alloc:1": {"sim_udid": A}, "alloc:2": {"sim_wanted": True, "sim_udid": None}}
try:
    b._sim_gate({A, B}); check("room for one more: 3 in use would be the third place", False)
except hm.SimWait as w:
    check("3 of 3 (A leased, B booted unleased, one being made): wait", (w.used, w.budget) == (3, 3))
    check("the reason names the numbers", "3 of 3" in str(w))
b.leases.pop("alloc:2")
try:
    b._sim_gate({A, B}); check("2 of 3: admitted", True)
except hm.SimWait:
    check("2 of 3: admitted", False)
try:
    b._sim_gate(None); check("an unreadable booted list fails open", True)
except hm.SimWait:
    check("an unreadable booted list fails open", False)
hm.SIM_BUDGET_FILE.unlink()
try:
    b._sim_gate({A, B, C, D}); check("no budget: no gate", True)
except hm.SimWait:
    check("no budget: no gate", False)

# -- allocate refuses BEFORE it makes anything, and leaves no lease behind
hm.SIM_BUDGET_FILE.write_text(json.dumps({"max": 1}))
b.leases = {}
b._sim_reading = lambda: {A}
made = []
hm._sim_create_boot = lambda *a, **k: made.append(a) or C
hm.Broker._save = lambda self: None
try:
    b.allocate(123, sim=True); check("allocate past the budget waits", False)
except hm.SimWait:
    check("allocate past the budget waits", True)
check("…having made no simulator", made == [])
check("…and holding no block", b.leases == {})
b._sim_reading = lambda: set()
b._commit = lambda lid, rec, gone, r: None
out = b.allocate(123, sim=True)
check("with room it leases the device", out.get("sim", {}).get("udid") == C and len(made) == 1)
r2 = b.allocate(124)
check("a lease without a simulator is never gated", "leaseId" in r2)

# -- the client waits, says so, then gives up with 75
replies = [(503, {"wait": "simulators 4 of 4 in use on this box"})] * 2 + [(200, {"leaseId": "x"})]
hm._call = lambda m, p, body=None, timeout=None: replies.pop(0)
t = [0.0]
err = io.StringIO()
with contextlib.redirect_stderr(err):
    st, out = hm._call_waiting("/allocate", {}, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0], wait_s=600)
check("asks again until there is room", (st, out.get("leaseId")) == (200, "x"))
check("says why it waits, once inside two minutes", err.getvalue().count("waiting for a simulator: simulators 4 of 4") == 1)
hm._call = lambda m, p, body=None, timeout=None: (503, {"wait": "simulators 4 of 4 in use on this box"})
t = [0.0]
err = io.StringIO()
code = None
with contextlib.redirect_stderr(err):
    try:
        hm._call_waiting("/allocate", {}, sleep=lambda s: t.__setitem__(0, t[0] + s), clock=lambda: t[0], wait_s=60)
    except SystemExit as e:
        code = e.code
check("past FBPORTS_SIM_WAIT: exit 75 (try later), never 1", code == 75)
check("…naming why", "no simulator after" in err.getvalue())
hm._call = lambda m, p, body=None, timeout=None: (500, {"error": "boom"})
check("any other answer is returned as is", hm._call_waiting("/allocate", {})[0] == 500)

sys.exit(1 if failed else 0)
