from data import ReqContext

from functools import lru_cache

@lru_cache(maxsize=512)
def get_blob_data(path:str, context:ReqContext) -> bytes: 
    import os
    from azure.storage.blob import BlobServiceClient
    from azure.core.exceptions import ResourceNotFoundError
    from azure.identity import DefaultAzureCredential

    ## Serve static file from Azure Blob Storage
    blob_service_client = None

    ## Setup Storage Connection
    blob_storage_connection = context.get_config_value("ui-storage-connection-string")
    if blob_storage_connection is not None:
        blob_service_client = BlobServiceClient.from_connection_string(blob_storage_connection)
    else:
        account_url = context.get_config_value("ui-storage-account-url")
        credential = context.get_config_value("ui-storage-account-key")
        if account_url is not None and credential is not None:
            blob_service_client = BlobServiceClient(account_url, credential=credential)


    ## Check for a Managed Identity Config
    account_name = context.get_config_value("ui-storage-account-name", os.environ.get("UI_STORAGE_ACCOUNT_NAME", None))
    if blob_service_client is None and account_name is not None:
        blob_service_client = BlobServiceClient(account_url=f"https://{account_name}.blob.core.windows.net", credential=DefaultAzureCredential())

    # Fallback to default storage account
    if blob_service_client is None:
        blob_storage_connection = os.environ.get("UI_STORAGE_CONNECTION_STRING")
        if blob_storage_connection is not None:
            blob_service_client = BlobServiceClient.from_connection_string(blob_storage_connection)
        else:
            account_url = os.environ.get("UI_STORAGE_ACCOUNT_URL")
            credential = os.environ.get("UI_STORAGE_ACCOUNT_KEY")
            if account_url is not None and credential is not None:
                blob_service_client = BlobServiceClient(account_url, credential=credential)
            else:
                account_name = os.environ.get("UI_STORAGE_ACCOUNT_NAME", os.environ.get("AZURE_STORAGE_ACCOUNT_NAME", None))
                if account_name is not None:
                    blob_service_client = BlobServiceClient(account_url=f"https://{account_name}.blob.core.windows.net")

    if blob_service_client is None:
        raise ValueError("Blob service not configured correctly.")

    ## Setup Storage Container
    container_name = context.get_config_value("ui-storage-container-name")
    if container_name is None:
        container_name = os.environ.get("UI_STORAGE_CONTAINER_NAME")

    if container_name is None:
        raise ValueError("Blob container name not configured correctly.")

    ## Load the Client + Download the file
    blob_client = blob_service_client.get_blob_client(container=container_name, blob=path)

    blob_data = None
    retries = 3
    while retries > 0:
        try:
            # encoding param is necessary for readall() to return str, otherwise it returns bytes
            downloader = blob_client.download_blob(max_concurrency=1, encoding=None)
            blob_data = downloader.readall()
            retries = 0
            break
        except ResourceNotFoundError:
            raise FileNotFoundError(f"Blob {path} does not exist.")
        except Exception as e:
            retries -= 1
    
    return blob_data