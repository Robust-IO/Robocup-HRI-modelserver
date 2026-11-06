#!/usr/bin/env python3
import sys
from urllib.request import urlopen

for port in (8001, 8002, 8003):
    try:
        with urlopen(f'http://127.0.0.1:{port}/health', timeout=2) as response:
            if response.status != 200:
                raise RuntimeError(f'HTTP {response.status}')
    except Exception as exc:
        print(f'{port}: {exc}', file=sys.stderr)
        sys.exit(1)
