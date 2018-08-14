#!/bin/bash

set -e
set -o pipefail

if [ "$EUID" -ne 0 ]; then
    echo "Please run as root."
    exit 1
fi

yum install -y mariadb mariadb-server
systemctl enable mariadb
systemctl start mariadb
systemctl status mariadb

mysql_secure_installation

echo -n "Ara database user password: "
read -s ara_password
echo ""

# TODO: restrict the privileges down??
echo "Setting ara user + privileges and database up."
mysql -u root -p << EOF
CREATE USER ara@'%' IDENTIFIED BY '${ara_password}';
CREATE DATABASE IF NOT EXISTS ara;
GRANT ALL PRIVILEGES ON ara.* TO 'ara'@'%';
FLUSH PRIVILEGES;
EOF
