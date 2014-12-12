#!/usr/bin/env sh

# This checks a given revision to make sure that it has a bug number
# in it, of the form "#123". It should  be used in your pretxncommit
# hook

hg log -r $1 --template {desc} | egrep -q "\#[0-9]+"
