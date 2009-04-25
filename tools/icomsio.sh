#!/bin/bash
#
# ICOM ID-RP* serial helper script
#
# Copyright 2008 Dan Smith <dsmith@danplanet.com>
#
# This script will scan the USB bus on this system and determine
# the product ID of any attached ICOM repeater modules.  It will
# unload and then reload the FTDI serial driver with the proper
# options to detect the device.  After that, it will determine the
# device name and link /dev/icom to that device for easy access.

LINK="icom"
VENDOR="0x0c26"
DEVICE=$(lsusb -d ${VENDOR}: | cut -d ' ' -f 6 | cut -d : -f 2)

if [ $(id -u) != 0 ]; then
    echo "This script must be run as root"
    exit 1
fi

if [ -z "$DEVICE" ]; then
    echo "No devices found"
    exit 1
fi

if echo $DEVICE | grep -q ' '; then
    echo "Multiple devices found:"
    for dev in $DEVICE; do
	echo $dev
    done

    exit 1
fi

modprobe -r ftdi_sio || {
    echo "Unable to unload ftdi_sio"
    exit 1
}

modprobe ftdi_sio vendor=${VENDOR} product=0x${DEVICE} || {
    echo "Failed to load ftdi_sio"
    exit 1
}

sleep 0.5

info=$(lsusb -d ${VENDOR}:0x${DEVICE})
bus=$(echo $info | cut -d ' ' -f 2 | sed 's/^0*//')
dev=$(echo $info | cut -d ' ' -f 4 | sed 's/^0*//')

for usbserial in /sys/class/tty/ttyUSB*; do
    driver=$(basename $(readlink -f ${usbserial}/device/driver))
    device=$(basename $usbserial)
    if [ "$driver" = "ftdi_sio" ]; then
	ln -sf /dev/${device} /dev/${LINK}
	echo "Device is /dev/${device} -> /dev/${LINK}"
	break
    fi
done

