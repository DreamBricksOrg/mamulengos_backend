from core.config import settings
import boto3
from botocore.client import Config
import uuid

# Definimos o endpoint region-specific
ENDPOINT = f"https://s3.{settings.AWS_REGION}.amazonaws.com"

s3_client = boto3.client(
    "s3",
    endpoint_url=ENDPOINT,
    region_name=settings.AWS_REGION,
    config=Config(signature_version="s3v4")
)

def public_url(key: str) -> str:
    return f"https://{settings.S3_BUCKET}.s3.{settings.AWS_REGION}.amazonaws.com/{key}"


def upload_fileobj(file_obj, key_prefix: str, extension: str = "png") -> str:
    """
    Faz upload de um file-like object para S3, retornando o key gerado com extensão.
    """
    key = f"{key_prefix}/{uuid.uuid4()}.{extension}"
    s3_client.upload_fileobj(
        file_obj,
        settings.S3_BUCKET,
        key,
        ExtraArgs={
            "ContentType": f"image/{extension}"
        }
    )
    return key


def create_presigned_upload(key_prefix: str, content_type: str, expires_in: int = 3600):
    key = f"{key_prefix}/{uuid.uuid4()}"
    url = s3_client.generate_presigned_url(
        ClientMethod="put_object",
        Params={
            "Bucket": settings.S3_BUCKET,
            "Key": key,
            "ContentType": content_type,
        },
        ExpiresIn=expires_in,
    )
    return {"url": url, "key": key}


def create_presigned_download(key: str, expires_in: int = 3600) -> str:
    return s3_client.generate_presigned_url(
        ClientMethod="get_object",
        Params={"Bucket": settings.S3_BUCKET, "Key": key},
        ExpiresIn=expires_in,
    )
