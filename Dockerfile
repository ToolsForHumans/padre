FROM ubuntu:18.04 as builder

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

RUN virtualenv -p /usr/bin/python3 /opt/padre/venv/

ADD . /opt/padre

RUN . /opt/padre/venv/bin/activate && pip install --no-cache-dir -r \
                                          /opt/padre/requirements.txt

RUN . /opt/padre/venv/bin/activate && pip install --no-cache-dir /opt/padre/

RUN . /opt/padre/venv/bin/activate && \
    cd /opt/padre/ && python \
                      /opt/padre/setup.py sdist \
                      -d /opt/padre/

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
COPY requirements.txt /opt/padre/requirements.txt

RUN mkdir -p /opt/padre/static/
RUN mkdir -p /etc/padre/prod/

RUN virtualenv -p /usr/bin/python3 /opt/padre/venv/

COPY --from=builder /opt/padre/*.tar.gz /opt/padre/
RUN . /opt/padre/venv/bin/activate && pip install --no-cache-dir -r \
                                          /opt/padre/requirements.txt
COPY templates/ /opt/padre/templates/
COPY scripts/start.sh /opt/padre/start.sh

RUN /opt/padre/venv/bin/pip3 install --no-cache-dir /opt/padre/*.tar.gz

WORKDIR /opt/padre
CMD ["/opt/padre/start.sh"]
