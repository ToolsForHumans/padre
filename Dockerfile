FROM ubuntu:18.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y --no-install-recommends \
                                      python3-dev \
                                      python3-pip \
                                      python3-setuptools \
                                      gcc \
                                      libldap2-dev \
                                      libsasl2-dev \
                                      build-essential \
                                      wget

RUN mkdir -p /opt/padre

ARG PACKAGE_PATH
ARG PACKAGE_NAME

COPY requirements.txt /opt/padre/requirements.txt
COPY $PACKAGE_PATH /opt/padre/$PACKAGE_NAME

RUN pip3 install --no-cache-dir \
                 -r /opt/padre/requirements.txt
RUN pip3 install --no-cache-dir /opt/padre/$PACKAGE_NAME

# TODO: add an actual start script.
WORKDIR /opt/padre
CMD ["/bin/bash"]
