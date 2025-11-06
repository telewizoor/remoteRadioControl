#!/bin/bash
# Script is running rigctld on the first available USB port - /dev/ttyUSB*

PORT=$(ls /dev/ttyUSB* 2>/dev/null | head -n 1)

if [ -z "$PORT" ]; then
    echo "There is no /dev/ttyUSB* device!"
    exit 1
fi

sudo ldconfig /usr/local/lib/
echo "Running rigctld on port: $PORT..."
exec /usr/local/bin/rigctld -m 1046 -r "$PORT" -s 38400
