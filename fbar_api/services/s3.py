"""S3 service client for presigned URL generation and object operations."""

import boto3
from botocore.config import Config
from botocore.exceptions import ClientError

from fbar_api.config import Settings


class S3Service:
    """Service client for S3 operations including presigned URL generation.

    Args:
        settings: Application settings containing AWS configuration.
    """

    def __init__(self, settings: Settings) -> None:
        """Initialize the S3 service with a boto3 client.

        Args:
            settings: Application settings with S3_BUCKET_NAME and
                      AWS_ENDPOINT_URL configuration.
        """
        self._settings = settings
        client_kwargs: dict = {
            "service_name": "s3",
        }
        if settings.AWS_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL

        self._client = boto3.client(**client_kwargs)

    def generate_presigned_url(
        self, bucket: str, key: str, ttl_seconds: int = 600
    ) -> str:
        """Generate a presigned URL for downloading an S3 object.

        Args:
            bucket: The S3 bucket name.
            key: The S3 object key.
            ttl_seconds: URL expiration time in seconds (default: 600 = 10 minutes).

        Returns:
            A presigned URL string for GET access to the object.
        """
        url: str = self._client.generate_presigned_url(
            ClientMethod="get_object",
            Params={"Bucket": bucket, "Key": key},
            ExpiresIn=ttl_seconds,
        )
        return url

    def object_exists(self, bucket: str, key: str) -> bool:
        """Check whether an object exists in S3.

        Uses head_object to verify existence without downloading the object.

        Args:
            bucket: The S3 bucket name.
            key: The S3 object key.

        Returns:
            True if the object exists, False otherwise.
        """
        try:
            self._client.head_object(Bucket=bucket, Key=key)
            return True
        except ClientError as e:
            error_code = e.response.get("Error", {}).get("Code", "")
            if error_code in ("404", "NoSuchKey"):
                return False
            raise

    def health_check(self) -> bool:
        """Check S3 connectivity by probing the configured bucket.

        Uses head_bucket with a 3-second timeout to verify S3 is reachable.

        Returns:
            True if S3 is reachable, False otherwise.
        """
        try:
            timeout_config = Config(
                connect_timeout=3,
                read_timeout=3,
            )
            # Create a one-off client with the timeout for the health check
            client_kwargs: dict = {
                "service_name": "s3",
                "config": timeout_config,
            }
            if self._settings.AWS_ENDPOINT_URL:
                client_kwargs["endpoint_url"] = self._settings.AWS_ENDPOINT_URL

            health_client = boto3.client(**client_kwargs)
            health_client.head_bucket(Bucket=self._settings.S3_BUCKET_NAME)
            return True
        except Exception:
            return False
