#!/usr/bin/env python3
"""The temp config a lease boots from (_write_injected_config). Pure: loads the
script as a module, writes a temp project, no daemon, no ports.

    python3 test/injected_config.py
"""
import importlib.machinery, importlib.util, json, pathlib, sys, tempfile

HM = pathlib.Path(__file__).resolve().parent.parent / "harbormaster"
loader = importlib.machinery.SourceFileLoader("harbormaster", str(HM))
spec = importlib.util.spec_from_loader("harbormaster", loader)
hm = importlib.util.module_from_spec(spec)
loader.exec_module(hm)

failed = 0
def check(name, ok):
    global failed
    print(("  ok  " if ok else "FAIL  ") + name)
    if not ok:
        failed += 1

# Tapuat's shape: a Next.js hosting target, and a hosting emulator declared.
FIREBASE_JSON = {
    "hosting": [{"target": "tapuat", "source": ".", "frameworksBackend": {"region": "us-central1"}}],
    "functions": {"source": "./functions"},
    "emulators": {"hosting": {"port": 5002}, "auth": {"port": 9099}, "firestore": {"port": 8080},
                  "functions": {"port": 5001}, "storage": {"port": 9199}, "singleProjectMode": True},
}
ports = hm._block_ports(15100)

with tempfile.TemporaryDirectory() as d:
    (pathlib.Path(d) / "firebase.json").write_text(json.dumps(FIREBASE_JSON))

    tmp = hm._write_injected_config(d, ports, ["auth", "firestore", "storage", "functions"])
    cfg = json.loads((pathlib.Path(d) / tmp).read_text())
    check("an --only without hosting drops the hosting block", "hosting" not in cfg)
    check("…and the hosting emulator", "hosting" not in cfg["emulators"])
    check("the asked emulators keep their leased ports",
          cfg["emulators"]["functions"]["port"] == ports["functions"] and cfg["emulators"]["auth"]["port"] == ports["auth"])
    check("functions config is untouched", cfg["functions"] == FIREBASE_JSON["functions"])

    tmp = hm._write_injected_config(d, ports, ["auth", "hosting"])
    cfg = json.loads((pathlib.Path(d) / tmp).read_text())
    check("an --only that asks for hosting keeps it", cfg.get("hosting") == FIREBASE_JSON["hosting"] and "hosting" in cfg["emulators"])

    tmp = hm._write_injected_config(d, ports)
    cfg = json.loads((pathlib.Path(d) / tmp).read_text())
    check("no --only (everything declared) keeps it, as before", "hosting" in cfg)

# 0.15.0: EVERY port the CLI may bind is on the block (the 2026-10-21 Studio
# races: logging 4501/4502 probed by two suites at once, tasks 9501 held by a
# walk2gether-expo CI suite).
def write(fj, only=None):
    with tempfile.TemporaryDirectory() as d:
        (pathlib.Path(d) / "firebase.json").write_text(json.dumps(fj))
        return json.loads((pathlib.Path(d) / hm._write_injected_config(d, ports, only)).read_text())

def all_ports(cfg):
    out = []
    for name, e in cfg["emulators"].items():
        if isinstance(e, dict):
            out += [v for k, v in e.items() if k in ("port", "websocketPort", "postgresPort")]
    return out

base = 15100
offs = hm.BLOCK_OFFSETS
check("the offset table: one port each, all inside the 20-port block",
      len(set(offs.values())) == len(offs) and all(0 <= o < hm.BLOCK for o in offs.values()))
check("…none on Metro or the caller's offsets (SSB's +12..+14)",
      hm.METRO_OFFSET not in offs.values() and not set(hm.CALLER_OFFSETS) & set(offs.values()))
check("…and every emulator the CLI can start has one",
      all(e in offs for e in (*hm.SERVICE_EMULATORS, *hm.IMPLICIT_EMULATORS))
      and all(n in offs for n in hm.SECOND_PORTS.values()))

# walk2gether-functions' shape: functions + eventarc declared, no tasks, ui on.
W2G = {"firestore": {"rules": "f.rules"}, "functions": {"source": "."}, "storage": {"rules": "s.rules"},
       "hosting": {"public": "p"},
       "emulators": {"auth": {}, "functions": {}, "firestore": {}, "ui": {"enabled": True}, "hub": {},
                     "logging": {}, "singleProjectMode": True, "storage": {}, "eventarc": {}}}
cfg = write(W2G, ["auth", "firestore", "functions", "storage"])
e = cfg["emulators"]
check("tasks gets a block port though undeclared (was the CLI default 9499 + probe)",
      e["tasks"]["port"] == ports["tasks"] == base + 19)
check("eventarc, logging, hub and ui are on the block",
      all(e[s]["port"] == ports[s] for s in ("eventarc", "logging", "hub", "ui")))
check("firestore's websocket is on the block", e["firestore"]["websocketPort"] == base + 10)
check("every port in the config is in the block, none on the caller's offsets",
      all(base <= p < base + hm.BLOCK and p - base not in hm.CALLER_OFFSETS for p in all_ports(cfg)))
check("no two emulators share a port", len(set(all_ports(cfg))) == len(all_ports(cfg)))

# impulse-functions' shape, but with the ui left out of the file: the CLI
# starts it anyway (a UI-supported emulator runs) on 4000 + probe.
NOUI = {"functions": {"source": "."}, "emulators": {"auth": {}, "firestore": {}, "functions": {}}}
e = write(NOUI)["emulators"]
check("an undeclared ui gets a block port", e["ui"]["port"] == ports["ui"])
check("…and is not switched on by us (the CLI's own rule decides)", "enabled" not in e["ui"])
check("tasks and eventarc are set for any config", e["tasks"]["port"] == ports["tasks"] and e["eventarc"]["port"] == ports["eventarc"])
off = write({"emulators": {"auth": {}, "ui": {"enabled": False}}})["emulators"]["ui"]
check("a declared ui is still switched on, as before", off.get("enabled") is True and off["port"] == ports["ui"])

# A product the CLI starts from the top level alone, no emulators.<x> entry.
TOP = {"firestore": {"rules": "f.rules"}, "dataconnect": {"source": "dc"}, "emulators": {}}
e = write(TOP)["emulators"]
check("a top-level-only firestore is given its port and websocket",
      e["firestore"]["port"] == ports["firestore"] and e["firestore"]["websocketPort"] == ports["firestore_websocket"])
check("dataconnect and its postgres are on the block (were 9399 and 5432)",
      e["dataconnect"]["port"] == base + 17 and e["dataconnect"]["postgresPort"] == base + 18)
check("no service emulator the project doesn't use is added (an entry would start it)",
      not {"storage", "database", "pubsub", "hosting", "apphosting", "functions", "auth"} & set(e))
e = write({"firestore": {}, "emulators": {"dataconnect": {"port": 9399}}}, ["firestore"])["emulators"]
check("a declared emulator's fixed port is replaced", e["dataconnect"]["port"] == ports["dataconnect"])

H = {"hosting": {"public": "p"}, "apphosting": {"rootDirectory": "."}, "emulators": {"auth": {}}}
e = write(H)["emulators"]
check("hosting and apphosting with no --only are on the block (were 5000/5002 + probe)",
      e["hosting"]["port"] == base + 15 and e["apphosting"]["port"] == base + 16)

try:
    write({"emulators": {"auth": {}, "newthing": {}}})
    check("a declared emulator with no offset is refused", False)
except ValueError as err:
    check("a declared emulator with no offset is refused, by name", "newthing" in str(err))
try:
    write({"emulators": {"auth": {}, "newthing": {}}}, ["auth"])
    check("…unless --only leaves it out", True)
except ValueError:
    check("…unless --only leaves it out", False)

print("FAILED" if failed else "all passed")
sys.exit(1 if failed else 0)
