#!/bin/bash
set -e

APP=weather
APPDIR=/opt/$APP

echo "==> Installing systemd service"
cp $APPDIR/$APP.service /etc/systemd/system/
systemctl daemon-reload
systemctl enable --now $APP

echo "==> Installing nginx config"
cp $APPDIR/$APP.nginx /etc/nginx/sites-available/$APP
ln -sf /etc/nginx/sites-available/$APP /etc/nginx/sites-enabled/$APP
nginx -t && systemctl reload nginx

echo ""
echo "Done. Check status with: systemctl status $APP"
