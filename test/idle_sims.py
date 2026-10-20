#!/usr/bin/env python3
"""An idle simulator no lease holds is shut down (0.13.0).

2026-10-20, the Mac Studio: "Impulse-agent", booted outside any lease by an
app's pinned simulator name, held two of ten cores for 32 hours with no app in
it. Pure: loads the script as a module; no daemon, no simctl.

    python3 test/idle_sims.py
"""
import importlib.machinery, importlib.util, os, pathlib, sys, tempfile

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

D = "/Users/s/Library/Developer/CoreSimulator/Devices"
IDLE, BUSY, LEASED, FRESH = ("1416CB52-6C71-4FFB-8EB3-96890D78BE6E", "491A6A1A-8BA7-4087-AF58-C0B27EE56576",
                             "B24875C2-9886-47A8-9865-531E5F34D25B", "36B17CBE-5E27-4516-83A8-734667B69A14")
ps = "\n".join([
    f"1-08:01:46 launchd_sim {D}/{IDLE}/data/var/run/launchd_bootstrap.plist",
    f"1-08:01:46 /Library/.../backboardd",   # a sim's daemon names no device: ignored
    f"10:00:00 launchd_sim {D}/{BUSY}/data/var/run/launchd_bootstrap.plist",
    f"02:00:00 {D}/{BUSY}/data/Containers/Bundle/Application/X/Walk2Gether.app/Walk2Gether",
    f"1-00:00:00 launchd_sim {D}/{LEASED}/data/var/run/launchd_bootstrap.plist",
    f"35:12 launchd_sim {D}/{FRESH}/data/var/run/launchd_bootstrap.plist",
])
booted = hm._booted_sims(ps)
check("every booted device is read", set(booted) == {IDLE, BUSY, LEASED, FRESH})
check("its uptime from launchd_sim", booted[IDLE]["upS"] == 32 * 3600 + 106)
check("an app running in it", booted[BUSY]["app"] is True and booted[IDLE]["app"] is False)

idle = hm.idle_unleased_sims(booted, {LEASED}, {IDLE: "Impulse-agent"}, hours=6)
check("only the idle, unleased, long-booted one", [x["udid"] for x in idle] == [IDLE])
check("named in the report", idle[0]["name"] == "Impulse-agent" and idle[0]["upH"] == 32.0)
check("a leased device is never touched, however long", all(x["udid"] != LEASED for x in idle))
check("one running an app is in use", all(x["udid"] != BUSY for x in idle))
check("a fresh boot is left to finish", all(x["udid"] != FRESH for x in idle))
check("0 turns it off", hm.idle_unleased_sims(booted, set(), {}, hours=0) == [])
check("etime forms", (hm._etime_s("35:12"), hm._etime_s("02:00:00"), hm._etime_s("1-00:00:01"), hm._etime_s("junk"))
      == (2112, 7200, 86401, None))

sys.exit(1 if failed else 0)
