#!/bin/bash
RIG=1046
BAUD=38400
PORT="/dev/serial/by-id/usb-Prolific_Technology_Inc._USB-Serial_Controller_AHBVb144J07-if00-port0"

if [ -z "$PORT" ]; then
    echo "There is no $PORT device!"
    exit 1
fi

sudo ldconfig /usr/local/lib/
echo "Running rigctld on port: $PORT..."
exec /usr/local/bin/rigctld -m $RIG -r "$PORT" -s $BAUD
