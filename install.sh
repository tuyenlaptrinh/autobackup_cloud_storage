#!/bin/bash
PATH=/www/server/panel/pyenv/bin:/bin:/sbin:/usr/bin:/usr/sbin:/usr/local/bin:/usr/local/sbin:~/bin
export PATH

PLUGIN_NAME="autobackup_cloud_storage"
PLUGIN_DIR="/www/server/panel/plugin/${PLUGIN_NAME}"
DATA_DIR="${PLUGIN_DIR}/data"
CRON_DIR="/etc/cron.d"
PYENV="/www/server/panel/pyenv/bin/pip"
PYBIN="/www/server/panel/pyenv/bin/python"
install_tmp='/tmp/bt_install.pl'

# Remove leftover left-menu entry from older versions (no longer registered on install)
_remove_menu()
{
    if [ -f "${PLUGIN_DIR}/register_menu.py" ]; then
        if [ -x "${PYBIN}" ]; then
            ${PYBIN} "${PLUGIN_DIR}/register_menu.py" uninstall >>$install_tmp 2>&1 || true
        elif command -v python3 >/dev/null 2>&1; then
            python3 "${PLUGIN_DIR}/register_menu.py" uninstall >>$install_tmp 2>&1 || true
        elif command -v python >/dev/null 2>&1; then
            python "${PLUGIN_DIR}/register_menu.py" uninstall >>$install_tmp 2>&1 || true
        fi
    fi
}

Install()
{
    echo "Installing Autobackup to Cloud..." > $install_tmp
    mkdir -p "${DATA_DIR}/logs"
    mkdir -p "${DATA_DIR}/tmp"
    chmod 700 "${DATA_DIR}"
    chmod +x "${PLUGIN_DIR}/backup_worker.py" 2>/dev/null || true
    chmod +x "${PLUGIN_DIR}/install.sh" 2>/dev/null || true

    # Prefer panel pyenv pip; fall back to system pip3
    if [ -x "${PYENV}" ]; then
        ${PYENV} install -q boto3 botocore google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib msal requests 2>>$install_tmp || true
    elif command -v pip3 >/dev/null 2>&1; then
        pip3 install -q boto3 botocore google-api-python-client google-auth google-auth-httplib2 google-auth-oauthlib msal requests 2>>$install_tmp || true
    fi

    # Ensure zip is available for archive creation
    if ! command -v zip >/dev/null 2>&1; then
        if command -v apt-get >/dev/null 2>&1; then
            apt-get install -y zip >/dev/null 2>&1 || true
        elif command -v yum >/dev/null 2>&1; then
            yum install -y zip >/dev/null 2>&1 || true
        fi
    fi

    # Drop main-menu shortcut if a previous version added it
    _remove_menu

    echo "Autobackup to Cloud installed successfully." > $install_tmp
}

Uninstall()
{
    echo "Uninstalling Autobackup to Cloud..." > $install_tmp
    _remove_menu
    # Remove cron entries created by this plugin
    rm -f ${CRON_DIR}/autobackup_cloud_storage_* 2>/dev/null || true
    rm -f ${CRON_DIR}/autobackup_drive_* 2>/dev/null || true
    rm -rf "${PLUGIN_DIR}"
    echo "Autobackup to Cloud uninstalled." > $install_tmp
}

action=$1
if [ "${action}" == "install" ]; then
    Install
elif [ "${action}" == "uninstall" ]; then
    Uninstall
else
    echo "Usage: $0 install|uninstall"
    exit 1
fi
