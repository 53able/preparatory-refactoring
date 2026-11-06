#!/usr/bin/env bash
set -eu
d="$(dirname "$0")"
if [ -d "$d/files" ] && [ -n "$(ls -A "$d/files")" ]; then cp -R "$d/files/." .; fi
git clone -q "$d/billing.bundle" billing
git -C billing remote remove origin
