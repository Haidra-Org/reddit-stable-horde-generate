from datetime import datetime
from horde.logger import logger
import boto3
from botocore.exceptions import ClientError

s3_client = boto3.client('s3', endpoint_url="https://a223539ccf6caa2d76459c9727d276e6.r2.cloudflarestorage.com")

def upload_image(filename):
    try:
        response = s3_client.upload_file(
            filename, "reddit", None,
            ExtraArgs={'ACL': 'public-read'}
        )
    except ClientError as e:
        logger.error(f"Error encountered while uploading {filename}: {e}")
        return False
    return True

def delete_image(filename):
    response = s3_client.delete_object(
        Bucket="reddit",
        Key=filename
    )
