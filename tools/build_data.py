#!/usr/bin/env python3

import collections
import contextlib
import datetime
import functools
import hashlib
import json
import os
import pathlib
import re
import shutil
import subprocess
import sys
import zipfile

from difflib import Differ
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / 'libs'))

from util import *

#############################################################################
ROOT_DIR = Path('.')

MANIFEST_FILE = ROOT_DIR / 'manifest.json'
STATUS_FILE = ROOT_DIR / 'ports_status.json'
PORTS_DIR = ROOT_DIR / 'ports'

LARGEST_FILE = (1024 * 1024 * 90)
CHUNK_SIZE = (1024 * 1024 * 50)

#############################################################################

GITIGNORE_HEADER = "# Autogenerated by tools/build_data.py"


def load_port(port_dir):
    if port_dir.name != name_cleaner(port_dir.name):
        error(port_dir.name, "Bad port directory name")
        return None

    git_ignore_file = port_dir / '.gitignore'
    git_ignores = []
    large_files = {}

    if git_ignore_file.is_file():
        with open(git_ignore_file, 'r') as fh:
            for line in fh:
                line = line.strip()
                if line == '' or line.startswith('#'):
                    continue

                git_ignores.append(line)

    # Create the manifest (an md5sum of all the files in the port, and an md5sum of those md5sums).
    temp = []
    paths = collections.deque([port_dir])

    while len(paths) > 0:
        path = paths.popleft()

        for file_name in path.iterdir():
            if file_name.name in ('.', '..', '.git', '.DS_Store', '.gitignore'):
                continue

            if file_name.name.startswith('._'):
                continue

            if file_name.is_dir():
                paths.append(file_name)
                continue

            if not file_name.is_file():
                continue

            if '.part.' in file_name.name:
                large_file_name, part_check, part_number = str(file_name).rsplit('.', 2)

                if file_name.name.rsplit('.', 2)[0] not in git_ignores:
                    git_ignores.append(file_name.name.rsplit('.', 2)[0])

                if part_check == 'part' and part_number.isdigit():
                    large_files.setdefault(large_file_name, []).append(str(file_name))
                    large_files[large_file_name].sort()

                continue

            if file_name.stat().st_size < LARGEST_FILE:
                continue

            if file_name.name not in git_ignores:
                git_ignores.append(file_name.name)

            large_files.setdefault(str(file_name), [])

    git_ignores.sort(key=lambda name: name.casefold())

    if len(git_ignores) > 0 or len(large_files) > 0:
        print('-' * 40)
        print("git_ignores = ", json.dumps(git_ignores, indent=4))
        print("large_files = ", json.dumps(large_files, indent=4))

        with open(git_ignore_file, 'w') as fh:
            print(GITIGNORE_HEADER, file=fh)
            for file_name in git_ignores:
                print(file_name, file=fh)

    return large_files


def split_large_files(port_dir, large_file_name, large_file_parts):
    part_number = 0
    with open(large_file_name, 'rb') as in_fh:
        finished = False
        while not finished:
            part_number += 1
            with open(f"{large_file_name}.part.{part_number:03d}", 'wb') as out_fh:
                data_amount = 0

                while data_amount < CHUNK_SIZE:
                    data = in_fh.read(1024 * 1024)

                    if len(data) == 0:
                        finished = True
                        break

                    data_amount += len(data)
                    out_fh.write(data)

    # Unlink extra files if they exist. :D
    part_number += 1
    while Path(f"{large_file_name}.part.{part_number:03d}").is_file():
        Path(f"{large_file_name}.part.{part_number:03d}").unlink()


def combine_large_files(port_dir, large_file_name, large_file_parts):
    with open(large_file_name, 'wb') as out_fh:
        for large_file_part in large_file_parts:
            with open(large_file_part, 'rb') as in_fh:
                while True:
                    data = in_fh.read(1024 * 1024)

                    if len(data) == 0:
                        break

                    out_fh.write(data)


def check_large_files(port_dir, large_files):
    for large_file_name, large_file_parts in large_files.items():
        large_file_name = Path(large_file_name)

        parts_md5 = None
        file_md5 = None

        if len(large_file_parts) > 0:
            parts_md5 = hash_files(large_file_parts)

        if large_file_name.is_file():
            file_md5 = hash_file(large_file_name)

        if file_md5 == None and parts_md5 == None:
            error(port_dir.name, "Wut?")
            continue

        print(f"{large_file_name}: {file_md5} == {parts_md5}")
        if file_md5 is None:
            combine_large_files(port_dir, large_file_name, large_file_parts)

        elif file_md5 != parts_md5:
            split_large_files(port_dir, large_file_name, large_file_parts)


def main(argv):
    for port_dir in sorted(PORTS_DIR.iterdir(), key=lambda x: str(x).casefold()):
        if not port_dir.is_dir():
            continue

        large_files = load_port(port_dir)
        check_large_files(port_dir, large_files)

    errors = 0
    warnings = 0
    for port_name, messages in MESSAGES.items():
        if port_name in updated_ports:
            continue

        print(f"Bad port {port_name}")
        if len(messages['warnings']) > 0:
            print("- Warnings:")
            print("  " + "\n  ".join(messages['warnings']) + "\n")
            warnings += 1

        if len(messages['errors']) > 0:
            print("- Errors:")
            print("  " + "\n  ".join(messages['errors']) + "\n")
            errors += 1

    if '--do-check' in argv:
        if errors > 0:
            return 255

        if warnings > 0:
            return 127

    return 0


if __name__ == '__main__':
    exit(main(sys.argv))
