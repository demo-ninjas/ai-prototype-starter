#!/bin/bash

APP_NAME="ai-chat-proxy"
RESOURCE_GROUP="hub-aueast"
VNET="hub-aueast-prodnet"

## Setup the Function App Network Rules
echo "Setting Environment Variables..."

## Get the path to the folder where this script is located
SCRIPT_DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" &> /dev/null && pwd )"
ENV_VARS_FILE="$SCRIPT_DIR/env-vars.json"

az functionapp config appsettings set -g $RESOURCE_GROUP -n $APP_NAME --settings @$ENV_VARS_FILE

