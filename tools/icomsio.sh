#!/usr/bin/env bash
#
# ICOM ID-RP* serial helper script
#
# Copyright 2009 Dan Smith <dsmith@danplanet.com>
#
# This script will scan the USB bus on this system and determine
# the product ID of any attached ICOM repeater modules.  It will
# unload and then reload the FTDI serial driver with the proper
# options to detect the device.  After that, it will determine the
# device name and link /dev/icom to that device for easy access.

LINK="icom"
VENDOR="0x0c26"
DEVICE=$(lsusb -d ${VENDOR}: | cut -d ' ' -f 6 | cut -d : -f 2 | sed -r 's/\n/ /g')

product_to_name() {
    local prod=$1

    if [ "$prod" = "0012" ]; then
        echo "ID-RP2000V TX"
    elif [ "$prod" = "0013" ]; then
        echo "ID-RP2000V RX"
    elif [ "$prod" = "0010" ]; then
        echo "ID-RP4000V TX"
    elif [ "$prod" = "0011" ]; then
        echo "ID-RP4000V RX"
    elif [ "$prod" = "000b" ]; then
        echo "ID-RP2D"
    elif [ "$prod" = "000c" ]; then
        echo "ID-RP2V TX"
    elif [ "$prod" = "000d" ]; then
        echo "ID-RP2V RX"
    else
        echo "Unknown module (id=${prod})"
    fi
}

if [ $(id -u) != 0 ]; then
    echo "This script must be run as root"
    exit 1
fi

if [ -z "$DEVICE" ]; then
    echo "No devices found"
    exit 1
fi

if echo $DEVICE | grep -q ' '; then
    echo "Multiple devices found.  Choose one:"
    i=0
    for dev in $DEVICE; do
        name=$(product_to_name $dev)
        echo "  ${i}: ${name}"
        i=$(($i + 1))
    done

    echo -n "> "
    read num

    array=($DEVICE)

    DEVICE=${array[$num]}
    if [ -z "$DEVICE" ]; then
        exit
    fi
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
        name=$(product_to_name $DEVICE)
        ln -sf /dev/${device} /dev/${LINK}
        echo "Device $name is /dev/${device} -> /dev/${LINK}"
        break
    fi
done
