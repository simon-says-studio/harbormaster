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

print("FAILED" if failed else "all passed")
sys.exit(1 if failed else 0)
