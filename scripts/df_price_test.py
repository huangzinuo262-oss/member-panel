#!/usr/bin/env python3
import json
import os
import sys
from urllib import request, error

URL = os.environ.get("DF_API_URL", "")
METHOD = os.environ.get("DF_API_METHOD", "GET").upper()
HEADERS = json.loads(os.environ.get("DF_API_HEADERS", "{}"))
BODY = os.environ.get("DF_API_BODY", "")

if not URL:
    print("Set DF_API_URL first", file=sys.stderr)
    sys.exit(1)

payload = BODY.encode("utf-8") if BODY else None
req = request.Request(URL, data=payload, method=METHOD)
for k, v in HEADERS.items():
    req.add_header(k, v)

try:
    with request.urlopen(req, timeout=30) as resp:
        print("STATUS", resp.status)
        print(json.dumps(dict(resp.headers), ensure_ascii=False, indent=2))
        raw = resp.read()
        try:
            print(json.dumps(json.loads(raw.decode("utf-8")), ensure_ascii=False, indent=2))
        except Exception:
            print(raw.decode("utf-8", errors="replace"))
except error.HTTPError as e:
    print("HTTP_ERROR", e.code, file=sys.stderr)
    print(e.read().decode("utf-8", errors="replace"), file=sys.stderr)
    sys.exit(2)
except Exception as e:
    print(f"ERROR {e}", file=sys.stderr)
    sys.exit(3)
