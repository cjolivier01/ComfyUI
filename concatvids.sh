#!/bin/bash
rm -f allfiles.txt
for i in $(find -maxdepth 1 -name "*.mp4" | shuf); do echo "file $i" >> allfiles.txt; done
rm -f all.mp4
ffmpeg -f concat -safe 0 -i allfiles.txt -c copy all.mp4
