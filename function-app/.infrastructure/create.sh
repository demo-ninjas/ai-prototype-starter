#!/bin/bash

APP_NAME="ai-chat-proxy"
RESOURCE_GROUP="hub-aueast"
VNET="hub-aueast-prodnet"

## Deploy the ARM template for this Function App
echo "Deploying the ARM template for the Function App..."
az deployment group create \
  --name "CreateAIChatFunctionApp" \
  --resource-group $RESOURCE_GROUP \
  --template-file "template.json" \
  --parameters "@parameters.json"

echo "Function App deployment completed."
echo "Don't forget to run the set-network-rules script as well..."