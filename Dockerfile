FROM ubuntu:18.04

ARG DEBIAN_FRONTEND=noninteractive

RUN apt-get update && apt-get install -y \
                                      python3-dev \
                                      python3-pip \
                                      python3-setuptools \
                                      python-virtualenv \
                                      gcc \
                                      git \
                                      libldap2-dev \
                                      libsasl2-dev \
                                      build-essential \
                                      wget

RUN mkdir -p /opt/padre/
RUN mkdir -p /etc/padre/prod/

ARG PACKAGE_PATH
ARG PACKAGE_NAME

RUN virtualenv -p /usr/bin/python3 /opt/padre/venv/

COPY requirements.txt /opt/padre/requirements.txt
COPY $PACKAGE_PATH /opt/padre/$PACKAGE_NAME
COPY scripts/start.sh /opt/padre/start.sh

RUN /opt/padre/venv/bin/pip3 install --no-cache-dir \
                                     -r /opt/padre/requirements.txt
RUN /opt/padre/venv/bin/pip3 install --no-cache-dir \
                                     /opt/padre/$PACKAGE_NAME

WORKDIR /opt/padre
CMD ["/opt/padre/start.sh"]
