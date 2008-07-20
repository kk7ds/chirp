#!/bin/bash

VERSION=$(cat build/version)
INCLUDE="COPYING"
TMP=$(mktemp -d)
EXCLUDE=""

RELDIR=chirp-${VERSION}

DST="${TMP}/${RELDIR}"

mkdir -p $DST

cp -rav --parents chirp/*.py csvdump/*.py $DST
cp -av *.py ${DST}

cp -rav $INCLUDE ${DST}

(cd $TMP && tar czf - $RELDIR) > ${RELDIR}.tar.gz

rm -Rf ${TMP}/${RELDIR}
