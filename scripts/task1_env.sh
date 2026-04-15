#!/usr/bin/env bash

# Runtime cache dirs for libraries that otherwise try to write under $HOME.
export MPLCONFIGDIR="${MPLCONFIGDIR:-$(pwd)/.runtime_cache/matplotlib}"
export PADDLE_PDX_CACHE_HOME="${PADDLE_PDX_CACHE_HOME:-$(pwd)/.runtime_cache/paddlex}"
export XDG_CACHE_HOME="${XDG_CACHE_HOME:-$(pwd)/.runtime_cache/xdg}"

mkdir -p "$MPLCONFIGDIR" "$PADDLE_PDX_CACHE_HOME" "$XDG_CACHE_HOME"

echo "MPLCONFIGDIR=$MPLCONFIGDIR"
echo "PADDLE_PDX_CACHE_HOME=$PADDLE_PDX_CACHE_HOME"
echo "XDG_CACHE_HOME=$XDG_CACHE_HOME"
