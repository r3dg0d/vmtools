#!/usr/bin/env python3
import os
import runpy
import sys
from pathlib import Path

os.environ.setdefault("SSL_CERT_FILE", "/etc/ssl/certs/ca-certificates.crt")
ROOT = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(ROOT))
if len(sys.argv) < 2:
    print("usage: run-tool.py <tool> ...", file=sys.stderr)
    raise SystemExit(2)
tool = sys.argv.pop(1)
sys.argv[0] = tool
runpy.run_module(f"{tool}.cli", run_name="__main__")
