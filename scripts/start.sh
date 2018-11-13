#!/bin/bash

set -e
set -o pipefail

if [ -z "${BOT}" ]; then
    echo "Required to set BOT environment variable."
    exit 1
fi

if [ -z "${VIRTUAL_ENV}" ]; then
    source "/opt/padre/venv/bin/activate"
fi

if [ "${BOT_PRODUCTION}" == "1" ]; then
    bot_conf="-c /etc/padre/base.yaml"
    bot_conf="${bot_conf} -c /etc/padre/secrets.yaml:DADDY_PASS"
    bot_conf="${bot_conf} -c /etc/padre/prod/:DADDY_PASS"
    bot_conf="${bot_conf} -c /etc/padre/${BOT}/:DADDY_PASS"
else
    bot_conf="-c $PWD/conf/base.yaml"
    bot_conf="${bot_conf} -c $PWD/conf/secrets.yaml:DADDY_PASS"
    bot_conf="${bot_conf} -c $PWD/conf/dev/:DADDY_PASS"
    bot_conf="${bot_conf} -c $PWD/conf/${BOT}/:DADDY_PASS"
fi

# TODO: further extract this some day...
if [ -f "${VIRTUAL_ENV}/etc/os_deploy/secrets.yaml" ]; then
    bot_really_secrets="-s ${VIRTUAL_ENV}/etc/os_deploy/secrets.yaml:DEPLOY_PASS"
else
    bot_really_secrets=""
fi

# TODO: further extract this some day...
if [ -d "${VIRTUAL_ENV}/etc/gdpadre/conf" ]; then
    bot_conf="${bot_conf} -c ${VIRTUAL_ENV}/etc/gdpadre/conf/base.yaml"
    if [ "${BOT_PRODUCTION}" == "1" ]; then
        bot_conf="${bot_conf} -c ${VIRTUAL_ENV}/etc/gdpadre/conf/prod.yaml:DADDY_PASS"
    else
        bot_conf="${bot_conf} -c ${VIRTUAL_ENV}/etc/gdpadre/conf/dev.yaml:DADDY_PASS"
    fi
    bot_conf="${bot_conf} -c ${VIRTUAL_ENV}/etc/gdpadre/conf/${BOT}/:DADDY_PASS"
fi

if [ "${BOT_BOOTSTRAP}" == "1" ]; then
    padre ${bot_really_secrets} ${bot_conf} --just-bootstrap
fi

exec padre ${bot_really_secrets} ${bot_conf}
