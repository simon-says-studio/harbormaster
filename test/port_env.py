#!/usr/bin/env python3
"""A function env value that names a leased port (_with_ports). Pure: loads the
script as a module, no daemon, no ports.

    python3 test/port_env.py
"""
import importlib.machinery, importlib.util, pathlib, sys

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

ports = hm._block_ports(15100)
env = hm._with_ports({
    "EMULATOR_PORT_FIRESTORE": "{port:firestore}",
    "EMULATOR_PORT_AUTH": "{port:auth}",
    "FIRESTORE_HOST": "127.0.0.1:{port:firestore}",
    "PLAIN": "no ports here",
    "TYPO": "{port:firestor}",
}, ports)
check("a bare reference is the leased port", env["EMULATOR_PORT_FIRESTORE"] == str(ports["firestore"]))
check("each service its own", env["EMULATOR_PORT_AUTH"] == str(ports["auth"]))
check("inside a value too", env["FIRESTORE_HOST"] == f"127.0.0.1:{ports['firestore']}")
check("a value with no reference is untouched", env["PLAIN"] == "no ports here")
check("an unknown service is left as written", env["TYPO"] == "{port:firestor}")

print("FAILED" if failed else "all passed")
sys.exit(1 if failed else 0)
