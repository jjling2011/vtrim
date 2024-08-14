#!/usr/bin/env bash

export VTRIM_CONFIG_DB="/my/path/to/clips.db"
export VTRIM_CONFIG_SOURCE="/my/video/folder/"
export VTRIM_CONFIG_DEST="/my/output/folder/"

./vtrim.py "$@"