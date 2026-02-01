#!/usr/bin/env python3
import json
import sys
import os
from datetime import datetime

MANIFEST_PATH = "custom_components/smarthub/manifest.json"

def bump_version(force_major=False):
    with open(MANIFEST_PATH, "r") as f:
        manifest = json.load(f)

    current_version = manifest.get("version", "0.0.0")
    print(f"Current version: {current_version}")
    
    # Strip any existing suffix like -alpha for calculation
    clean_version = current_version.split("-")[0]
    major, minor, patch = map(int, clean_version.split("."))

    now = datetime.now()
    current_month = now.month

    new_major = major
    new_minor = current_month
    new_patch = patch

    if force_major:
        new_major += 1
        new_minor = current_month
        new_patch = 0
        print(f"Forcing Major bump: {major} -> {new_major}")
    elif new_minor != minor:
        # Month changed (or first time setting month-based minor)
        # Note: If year changes, month goes back to 1, so != works.
        new_patch = 0
        print(f"Month changed (Minor bump): {minor} -> {new_minor}")
    else:
        new_patch += 1
        print(f"Patch bump: {patch} -> {new_patch}")

    new_version_base = f"{new_major}.{new_minor}.{new_patch}"
    new_version_tag = f"v{new_version_base}-alpha"
    
    # Update manifest (we store the clean version or the alpha version? 
    # Usually manifest has the clean version or matches the tag. 
    # User said "create RELEASE CANDIDATES on merge", so let's put the alpha version in manifest)
    manifest["version"] = f"{new_version_base}-alpha"

    with open(MANIFEST_PATH, "w") as f:
        json.dump(manifest, f, indent=2)
        f.write("\n") # Add newline at end of file

    print(f"::set-output name=new_version::{new_version_base}")
    print(f"::set-output name=new_tag::{new_version_tag}")
    print(f"Bumped version to: {manifest['version']}")

if __name__ == "__main__":
    force_major_env = os.environ.get("FORCE_MAJOR", "false").lower()
    force_major = force_major_env == "true"
    bump_version(force_major)
