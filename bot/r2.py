from datetime import datetime
from bot.logger import logger
import boto3
from botocore.exceptions import ClientError

s3_client = boto3.client('s3', endpoint_url="https://a223539ccf6caa2d76459c9727d276e6.r2.cloudflarestorage.com")

def upload_image(filename):
    try:
        response = s3_client.upload_file(
            filename, "reddit", filename,
            ExtraArgs={'ACL': 'public-read'}
        )
    except ClientError as e:
        logger.error(f"Error encountered while uploading {filename}: {e}")
        return False
    return generate_img_download_url(filename)

def delete_image(filename):
    response = s3_client.delete_object(
        Bucket="reddit",
        Key=filename
    )


@logger.catch(reraise=True)
def generate_presigned_url(client_method, method_parameters, expires_in):
    """
    Generate a presigned Amazon S3 URL that can be used to perform an action.

    :param s3_client: A Boto3 Amazon S3 client.
    :param client_method: The name of the client method that the URL performs.
    :param method_parameters: The parameters of the specified client method.
    :param expires_in: The number of seconds the presigned URL is valid for.
    :return: The presigned URL.
    """
    try:
        url = s3_client.generate_presigned_url(
            ClientMethod=client_method,
            Params=method_parameters,
            ExpiresIn=expires_in
        )
    except ClientError:
        logger.exception(
            f"Couldn't get a presigned URL for client method {client_method}", )
        raise
    # logger.debug(url)
    return url

    
def generate_img_download_url(filename):
    return generate_presigned_url("get_object", {'Bucket': "reddit", 'Key': filename}, 604799)
