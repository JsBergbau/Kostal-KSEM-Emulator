#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"


sudo install -m 644 "$DIR/ksem.service" /etc/systemd/system/ksem.service
systemctl daemon-reload
systemctl enable ksem.service
systemctl start ksem.service
