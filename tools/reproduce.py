#!/usr/bin/env python3
"""Rebuild .55, compare the frozen release, and run CPU checks; never flash USB."""
import argparse
import hashlib
import importlib.metadata
import json
from pathlib import Path
import subprocess
import sys

from prepare_baselines import prepare

ROOT = Path(__file__).resolve().parents[1]
EXPECTED_SHA256 = '01abe933e35a26572aa3fac63c741d69ae3bda55023a74de35796c9ade94373c'
EXPECTED_SIZE = 32472


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--stock', type=Path, default=ROOT / 'vendor/Ver.04.bin')
    args = parser.parse_args()
    for package, expected in [('ziglang', '0.17.1'), ('unicorn', '2.1.4')]:
        actual = importlib.metadata.version(package)
        if actual != expected:
            raise SystemExit(f'{package}: expected {expected}, found {actual}; install requirements.txt.')
    stock = args.stock.resolve()
    if not stock.is_file():
        raise SystemExit('Stock input missing. Run python3 tools/fetch_stock.py or pass --stock.')
    prepare(stock)
    subprocess.run([sys.executable, str(ROOT / 'src/build.py'), str(stock)], check=True, cwd=ROOT)
    image = (ROOT / 'src/dist/GTE_ALL_EXP055.bin').read_bytes()
    released = (ROOT / 'release/v0.55-exp/GTE_ALL_EXP055.bin').read_bytes()
    if (len(image) != EXPECTED_SIZE or hashlib.sha256(image).hexdigest() != EXPECTED_SHA256
            or image != released):
        raise SystemExit('Rebuilt .55 differs from the frozen release; refusing verification claim.')
    subprocess.run([sys.executable, str(ROOT / 'src/verify.py'), str(stock)], check=True, cwd=ROOT)
    report = json.loads((ROOT / 'src/dist/verification.json').read_text())
    if report.get('status') != 'PASS' or report.get('check_count') != 8208:
        raise SystemExit('Unexpected verification result; inspect src/dist/verification.json.')
    print('PASS: byte-identical .55 release, four historical hashes, 8208 CPU checks. No hardware accessed.')


if __name__ == '__main__':
    main()
