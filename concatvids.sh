rm -f allfiles.txt
for i in $(find -maxdepth 1 -name "*.mp4" | shuf); do echo "file $i" >> allfiles.txt; done
