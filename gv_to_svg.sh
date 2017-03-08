#!/usr/bin/env bash

set -e

for file in `ls gradle_graphs/*.gv`; do
    file=`echo $file | sed 's/\.gv$//'`
    cmd="dot $file.gv -Tsvg -o $file.svg"
    echo $cmd
    $cmd
done
