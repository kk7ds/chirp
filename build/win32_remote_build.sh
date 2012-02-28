#!/bin/bash -x

VERSION=$(cat build/version)
HOST=$1
shift

if [ -z "$HOST" ]; then
    echo "Usage: $0 [host]"
    exit 1
fi

temp_dir() {
    ssh $HOST "mktemp -d /tmp/${1}.XXXXXX"
}

copy_source() {
    tmp=$1
    hg status -nmca > .files

    rsync -av --files-from=.files . $HOST:$tmp
}

do_build() {
    tmp=$1
    out=$2

    shift
    shift

    ssh $HOST "cd $tmp && ./build/make_win32_build.sh $out $* && chmod 755 $out/*"
}

grab_builds() {
    out=$1

    scp -r "$HOST:$out/*" dist
}

cleanup () {
    tmp=$1

    ssh $HOST "rm -Rf $tmp"
}

sed -i 's/^CHIRP_VERSION.*$/CHIRP_VERSION=\"'$VERSION'\"/' chirp/__init__.py

tmp1=$(temp_dir chirp_build)
tmp2=$(temp_dir chirp_output)
copy_source $tmp1
do_build $tmp1 $tmp2 $*
grab_builds $tmp2
#cleanup $tmp1
