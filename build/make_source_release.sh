#!/usr/bin/env bash

VERSION=$(cat build/version)
INCLUDE="COPYING"
TMP=$(mktemp -d)
EXCLUDE=""

sed -i 's/^CHIRP_VERSION.*$/CHIRP_VERSION=\"'$VERSION'\"/' chirp/__init__.py

RELDIR=chirp-${VERSION}

DST="${TMP}/${RELDIR}"

mkdir -p $DST

cp -rav --parents chirp/*.py chirp/drivers/*.py csvdump/*.py chirp/ui/* $DST
cp -av *.py ${DST}

cp -rav $INCLUDE ${DST}

(cd $TMP && tar czf - $RELDIR) > ${RELDIR}.tar.gz

rm -Rf ${TMP}/${RELDIR}
