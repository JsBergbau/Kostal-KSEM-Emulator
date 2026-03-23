#!/bin/bash

DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"


sudo install -m 644 /etc/systemd/system/
systemctl daemon-reload
systemctl enable ksem.service
systemctl start ksem.service
