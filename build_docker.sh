#!/bin/bash

set -e
set -x

rm -rf dist
mkdir dist
python setup.py sdist

tag="padre:latest"
dist=$(ls dist/*.tar.gz)
if [ -z "$dist" ]; then
    echo "Nothing was built!"
    exit 1
fi

docker build --tag $tag --build-arg PACKAGE_PATH=$dist \
             --build-arg PACKAGE_NAME=$(basename $dist) .
