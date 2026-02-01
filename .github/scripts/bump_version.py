#!/usr/bin/env python3
import json
import sys
import os
import subprocess
import re
import argparse
from typing import Optional

MANIFEST_PATH = "custom_components/smarthub/manifest.json"

def get_latest_tag() -> str:
    try:
        # Get the latest tag reachable from the current commit
        cmd = ["git", "describe", "--tags", "--abbrev=0"]
        result = subprocess.run(cmd, capture_output=True, text=True, check=True)
        return result.stdout.strip()
    except subprocess.CalledProcessError:
        print("No tags found. Defaulting to 0.0.0")
        return "v0.0.0"

def calculate_next_version(current_tag: str, force_major: bool = False) -> str:
    # Regex to match v1.2.3 or v1.2.3-alpha or 1.2.3
    # Group 1,2,3 are Maj, Min, Patch. Group 4 is optional suffix (e.g. alpha)
    pattern = re.compile(r"^v?(\d+)\.(\d+)\.(\d+)(?:-(.+))?$")
    match = pattern.match(current_tag)
    
    if not match:
        raise ValueError(f"Invalid version format: {current_tag}")
    
    major = int(match.group(1))
    minor = int(match.group(2))
    patch = int(match.group(3))
    suffix = match.group(4)
    
    is_alpha = suffix is not None

    new_major = major
    new_minor = minor
    new_patch = patch

    if force_major:
        new_major += 1
        new_minor = 0
        new_patch = 0
    elif is_alpha:
        new_patch += 1
    else:
        new_minor += 1
        new_patch = 0

    return f"{new_major}.{new_minor}.{new_patch}-alpha"

def bump_version(force_major: bool = False, write_manifest: bool = False) -> None:
    current_tag = get_latest_tag()
    print(f"Current tag: {current_tag}")

    try:
        new_version_full = calculate_next_version(current_tag, force_major)
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)
        
    new_version_tag = f"v{new_version_full}"
    
    if write_manifest:
        # Update manifest
        with open(MANIFEST_PATH, "r") as f:
            manifest = json.load(f)
        
        manifest["version"] = new_version_full

        with open(MANIFEST_PATH, "w") as f:
            json.dump(manifest, f, indent=2)
            f.write("\n")
        print(f"Bumped manifest version to: {manifest['version']}")
    else:
        print(f"Calculated version: {new_version_full} (Manifest not updated)")

    if "GITHUB_OUTPUT" in os.environ:
        with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
            print(f"new_version={new_version_full}", file=fh)
            print(f"new_tag={new_version_tag}", file=fh)
    else:
        print(f"new_version={new_version_full}")
        print(f"new_tag={new_version_tag}")

if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--force-major", action="store_true", help="Force a major version bump")
    parser.add_argument("--write", action="store_true", help="Write the new version to manifest.json")
    parser.add_argument("--set-version", help="Explicitly set the version (skip calculation)")
    args = parser.parse_args()
    
    # Check env var for backward compatibility or CI ease
    force_major_env = os.environ.get("FORCE_MAJOR", "false").lower() == "true"
    force_major = args.force_major or force_major_env
    
    if args.set_version:
        # If specific version provided, use it directly
        new_version_base = args.set_version
        new_version_tag = f"v{new_version_base}"
        
        if args.write:
            with open(MANIFEST_PATH, "r") as f:
                manifest = json.load(f)
            manifest["version"] = new_version_base
            with open(MANIFEST_PATH, "w") as f:
                json.dump(manifest, f, indent=2)
                f.write("\n")
            print(f"Updated manifest version to: {manifest['version']}")
        else:
            print(f"Proposed version: {new_version_base} (Manifest not updated)")
            
        if "GITHUB_OUTPUT" in os.environ:
            with open(os.environ["GITHUB_OUTPUT"], "a") as fh:
                print(f"new_version={new_version_base}", file=fh)
                print(f"new_tag={new_version_tag}", file=fh)
        else:
            print(f"new_version={new_version_base}")
            print(f"new_tag={new_version_tag}")
            
    else:
        bump_version(force_major=force_major, write_manifest=args.write)