#!/usr/bin/env bash
find "$(dirname "$0")/../logs" -name '*.log' -mtime +180 -delete 2>/dev/null
