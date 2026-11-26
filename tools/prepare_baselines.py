#!/usr/bin/env python3
"""Build hash-locked historical CPU comparison images, not install recommendations."""
import argparse
import hashlib
from pathlib import Path
import shutil
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
STOCK_SHA256 = '28c30d003a8b2a399cf7c019dfc400dcae751c24dc17bc653f325244a3310c09'
BASELINES = {
    '0.51': ('GTE_ALL_EXP051.bin', 'd8e587ed33e40c3e806f447e192c08cbb971d6716cbf8504f24bcb17c63cd92d'),
    '0.52': ('GTE_ALL_EXP052.bin', 'fcda2aa0e30f2644ae20700598967fcff25fd032f77b72fd8dfe4cda82c83cd6'),
    '0.53': ('GTE_ALL_EXP053.bin', 'f4d1828e27f09b1b133680d02cbb061c33a1c1f295f9ffd0e74a827cdb458308'),
    '0.54': ('GTE_ALL_EXP054.bin', '1cad2387744d792c6aa0a071b94e4f6330306c6fb6ad2f5a2426ed8f13a4352a'),
}


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def prepare(stock):
    stock = stock.resolve()
    if sha(stock) != STOCK_SHA256:
        raise SystemExit('Wrong stock image; no baseline build performed.')
    output = ROOT / 'src/baseline'
    output.mkdir(parents=True, exist_ok=True)
    for version, (name, expected) in BASELINES.items():
        destination = output / name
        if destination.exists() and sha(destination) == expected:
            print(f'{version}: existing comparison verified', flush=True)
            continue
        source = ROOT / 'history' / version
        subprocess.run([sys.executable, str(source / 'build.py'), str(stock)], cwd=ROOT, check=True)
        built = source / 'dist' / name
        if sha(built) != expected:
            raise SystemExit(f'{version}: comparison differs from the frozen historical image.')
        shutil.copyfile(built, destination)
        print(f'{version}: rebuilt comparison hash verified', flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('stock', type=Path)
    prepare(parser.parse_args().stock)


if __name__ == '__main__':
    main()
