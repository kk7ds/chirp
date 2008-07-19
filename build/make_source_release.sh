#!/bin/bash

LOCAL_VERSION=
eval $(cat mainapp.py | grep ^DRATS_VERSION | sed 's/ //g')
#VERSION=${DRATS_VERSION}${LOCAL_VERSION}
VERSION=0.1.1
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
