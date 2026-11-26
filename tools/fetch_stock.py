#!/usr/bin/env python3
"""Download the exact official .04 build input; never access adapter USB."""
import argparse
import hashlib
import os
from pathlib import Path
import urllib.request

ROOT = Path(__file__).resolve().parents[1]
URL = 'https://stkb.co.jp/file/Ver.04.bin'
SHA256 = '28c30d003a8b2a399cf7c019dfc400dcae751c24dc17bc653f325244a3310c09'
SIZE = 13956


def validate(data):
    if len(data) != SIZE or hashlib.sha256(data).hexdigest() != SHA256:
        raise ValueError('Official input differs from the pinned Ver.04 image; refusing it.')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('destination', nargs='?', type=Path, default=ROOT / 'vendor/Ver.04.bin')
    args = parser.parse_args()
    dest = args.destination.resolve()
    if dest.exists():
        validate(dest.read_bytes())
        print('Existing official Ver.04 input verified.')
        return
    with urllib.request.urlopen(URL, timeout=30) as response:
        data = response.read(1024 * 1024 + 1)
    validate(data)
    dest.parent.mkdir(parents=True, exist_ok=True)
    temp = dest.with_name(dest.name + '.part')
    try:
        with temp.open('xb') as stream:
            stream.write(data)
        os.replace(temp, dest)
    finally:
        temp.unlink(missing_ok=True)
    print('Downloaded and verified official Ver.04 input.')


if __name__ == '__main__':
    main()
