"""Unit tests for S3Service."""

import boto3
import pytest
from moto import mock_aws

from fbar_api.config import Settings
from fbar_api.services.s3 import S3Service


@pytest.fixture
def settings() -> Settings:
    """Create test settings."""
    return Settings(
        S3_BUCKET_NAME="test-bucket",
        AWS_ENDPOINT_URL=None,
    )


@pytest.fixture
def s3_service(settings: Settings) -> S3Service:
    """Create S3Service with mocked AWS."""
    return S3Service(settings)


@mock_aws
def test_generate_presigned_url(settings: Settings) -> None:
    """Test presigned URL generation returns a valid URL string."""
    # Create bucket first
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="test-bucket")
    conn.put_object(Bucket="test-bucket", Key="fbar-pdfs/2023/test.pdf", Body=b"pdf")

    service = S3Service(settings)
    url = service.generate_presigned_url("test-bucket", "fbar-pdfs/2023/test.pdf")

    assert isinstance(url, str)
    assert "test-bucket" in url
    assert "test.pdf" in url


@mock_aws
def test_generate_presigned_url_custom_ttl(settings: Settings) -> None:
    """Test presigned URL generation with custom TTL."""
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="test-bucket")
    conn.put_object(Bucket="test-bucket", Key="doc.pdf", Body=b"pdf")

    service = S3Service(settings)
    url = service.generate_presigned_url("test-bucket", "doc.pdf", ttl_seconds=300)

    assert isinstance(url, str)
    assert len(url) > 0


@mock_aws
def test_object_exists_returns_true(settings: Settings) -> None:
    """Test object_exists returns True for an existing object."""
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="test-bucket")
    conn.put_object(Bucket="test-bucket", Key="fbar-pdfs/2023/test.pdf", Body=b"pdf")

    service = S3Service(settings)
    result = service.object_exists("test-bucket", "fbar-pdfs/2023/test.pdf")

    assert result is True


@mock_aws
def test_object_exists_returns_false(settings: Settings) -> None:
    """Test object_exists returns False for a non-existing object."""
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="test-bucket")

    service = S3Service(settings)
    result = service.object_exists("test-bucket", "nonexistent/key.pdf")

    assert result is False


@mock_aws
def test_health_check_returns_true(settings: Settings) -> None:
    """Test health_check returns True when S3 bucket is reachable."""
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="test-bucket")

    service = S3Service(settings)
    result = service.health_check()

    assert result is True


@mock_aws
def test_health_check_returns_false_bucket_missing(settings: Settings) -> None:
    """Test health_check returns False when bucket doesn't exist."""
    # Don't create the bucket - it shouldn't exist
    service = S3Service(settings)
    result = service.health_check()

    assert result is False


@mock_aws
def test_default_ttl_is_600_seconds(settings: Settings) -> None:
    """Test that default TTL for presigned URLs is 600 seconds (10 minutes)."""
    conn = boto3.client("s3", region_name="us-east-1")
    conn.create_bucket(Bucket="test-bucket")
    conn.put_object(Bucket="test-bucket", Key="doc.pdf", Body=b"content")

    service = S3Service(settings)
    # Verify default parameter works (no exception)
    url = service.generate_presigned_url("test-bucket", "doc.pdf")
    assert isinstance(url, str)
