#!/usr/bin/env bash

set -x

VERSION=$(cat build/version)
HOST=$1
shift

SSH='ssh -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null'
SCP='scp -oStrictHostKeyChecking=no -oUserKnownHostsFile=/dev/null'

if [ -z "$HOST" ]; then
    echo "Usage: $0 [host]"
    exit 1
fi

temp_dir() {
    $SSH $HOST "mktemp -d /tmp/${1}.XXXXXX"
}

copy_source() {
    tmp=$1
    hg status -nmca > .files

    rsync -e "$SSH" -av --files-from=.files . $HOST:$tmp
}

do_build() {
    tmp=$1
    out=$2

    shift
    shift

    $SSH $HOST "cd $tmp && ./build/make_win32_build.sh $out $* && chmod 755 $out/*"
}

grab_builds() {
    out=$1

    $SCP -r "$HOST:$out/*" dist
}

cleanup () {
    tmp=$1

    $SSH $HOST "rm -Rf $tmp"
}

sed -i 's/^CHIRP_VERSION.*$/CHIRP_VERSION=\"'$VERSION'\"/' chirp/__init__.py

tmp1=$(temp_dir chirp_build)
tmp2=$(temp_dir chirp_output)
copy_source $tmp1
do_build $tmp1 $tmp2 $*
grab_builds $tmp2
cleanup $tmp1
