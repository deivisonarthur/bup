#!/usr/bin/env bash
. ./wvtest-bup.sh

set -o pipefail

top="$(WVPASS pwd)" || exit $?
tmpdir="$(WVPASS wvmktempdir)" || exit $?

bup() { "$top/bup" "$@"; }

WVPASS cd "$tmpdir"

WVSTART "bup get (local)"
export BUP_DIR=get-src
WVPASS bup init
WVPASS cp -a "$top/lib" src
WVPASS bup index src
WVPASS bup save -n src src
export BUP_DIR=get-dest
WVPASS bup init
WVPASS bup get -n fetched-src -s get-src src/latest
WVPASS bup restore -C restore "/fetched-src/latest$(pwd)/src"
WVPASS "$top/t/compare-trees" -c src/ restore/src/

WVSTART "bup get (remote)"
WVPASS bup get -r -:"$(pwd)/get-dest" -n remote-stored-src -s get-src src/latest
WVPASS rm -rf restore
WVPASS bup restore -C restore "/remote-stored-src/latest$(pwd)/src"
WVPASS "$top/t/compare-trees" -c src/ restore/src/

WVSTART "bup on get"
WVPASS bup on - get -n on-fetched-src -s get-src src/latest
WVPASS rm -rf restore
WVPASS bup restore -C restore "/on-fetched-src/latest$(pwd)/src"
WVPASS "$top/t/compare-trees" -c src/ restore/src/

WVPASS rm -rf "$tmpdir"
