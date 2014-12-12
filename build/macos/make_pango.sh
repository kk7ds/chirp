#!/usr/bin/env bash

make_pango_modules() {
	local src=$1
	local dst=$2
	local sf=${src}/etc/pango/pango.modules
	local df=${dst}/etc/pango/pango.modules

	cat $sf | sed 's/\/opt\/.*\/lib/..\/Resources/' > $df
}

make_pango_rc() {
	local src=$1
	local dst=$2
	local sf=${src}/etc/pango/pangorc
	local df=${dst}/etc/pango/pangorc

	cat $sf | sed 's/\/opt\/.*\/etc/.\/etc/' > $df
}

make_pangox_aliases() {
	local src=$1
	local dst=$2

	cp ${src}/etc/pango/pangox.aliases ${dst}/etc/pango
}

usage() {
	echo 'Usage: make_pango.sh [PATH_TO_MACPORTS] [PATH_TO_APP]'
	echo 'Example:'
	echo '  make_pango.sh /opt/local dist/d-rats.app'
}

if [ -z "$1" ]; then
	usage
	exit 1
fi

if [ -z "$2" ]; then
	usage
	exit 1
fi

base=$1
app="$2/Contents/Resources"

mkdir -p ${app}/etc/pango

make_pango_modules $base $app
make_pango_rc $base $app
make_pangox_aliases $base $app
