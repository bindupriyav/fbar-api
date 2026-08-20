#!/usr/bin/env python3
"""
S3 PDF Upload Script

Creates the S3 bucket (if not exists) with SSE-KMS encryption and
block-public-access, then uploads all 50 FBAR PDF files using the
key pattern: fbar-pdfs/{taxYear}/FBAR_{bsaId}.pdf

Usage:
    python scripts/load_s3.py --endpoint-url http://localhost:4566
"""

import argparse
import json
import os
import sys

import boto3
from botocore.exceptions import ClientError

BUCKET_NAME = "irs-cm-fbar-documents-dev"
FILINGS_JSON = os.path.join(os.path.dirname(__file__), "..", "synthetic_fbar_filings.json")
PDFS_DIR = os.path.join(os.path.dirname(__file__), "..", "fbar_pdfs", "pdfs")


def parse_args():
    parser = argparse.ArgumentParser(description="Upload FBAR PDFs to S3")
    parser.add_argument(
        "--endpoint-url",
        default=None,
        help="AWS endpoint URL (e.g., http://localhost:4566 for LocalStack)",
    )
    return parser.parse_args()


def create_s3_client(endpoint_url=None):
    kwargs = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.client("s3", **kwargs)


def bucket_exists(s3_client, bucket_name):
    try:
        s3_client.head_bucket(Bucket=bucket_name)
        return True
    except ClientError as e:
        error_code = int(e.response["Error"]["Code"])
        if error_code == 404:
            return False
        raise


def create_bucket(s3_client, bucket_name, endpoint_url=None):
    """Create bucket with SSE-KMS encryption and block-public-access."""
    # Create the bucket
    create_kwargs = {"Bucket": bucket_name}

    # For non-us-east-1 regions, a LocationConstraint is needed.
    # For LocalStack or default, we skip it to avoid issues.
    if not endpoint_url:
        region = s3_client.meta.region_name
        if region and region != "us-east-1":
            create_kwargs["CreateBucketConfiguration"] = {
                "LocationConstraint": region
            }

    s3_client.create_bucket(**create_kwargs)

    # Enable SSE-KMS encryption
    s3_client.put_bucket_encryption(
        Bucket=bucket_name,
        ServerSideEncryptionConfiguration={
            "Rules": [
                {
                    "ApplyServerSideEncryptionByDefault": {
                        "SSEAlgorithm": "aws:kms",
                    },
                    "BucketKeyEnabled": True,
                }
            ]
        },
    )

    # Block all public access
    s3_client.put_public_access_block(
        Bucket=bucket_name,
        PublicAccessBlockConfiguration={
            "BlockPublicAcls": True,
            "IgnorePublicAcls": True,
            "BlockPublicPolicy": True,
            "RestrictPublicBuckets": True,
        },
    )

    print(f"Created bucket '{bucket_name}' with SSE-KMS encryption and block-public-access")


def load_filings_metadata(filings_path):
    """Load synthetic filings JSON to get bsaId -> taxYear mapping."""
    with open(filings_path, "r", encoding="utf-8") as f:
        data = json.load(f)
    return {filing["bsaId"]: filing["taxYear"] for filing in data["filings"]}


def upload_pdfs(s3_client, bucket_name, filings_metadata, pdfs_dir):
    """Upload PDF files using key pattern fbar-pdfs/{taxYear}/FBAR_{bsaId}.pdf."""
    uploaded_count = 0

    for bsa_id, tax_year in filings_metadata.items():
        filename = f"FBAR_{bsa_id}.pdf"
        local_path = os.path.join(pdfs_dir, filename)

        if not os.path.isfile(local_path):
            print(f"WARNING: PDF file not found: {local_path}", file=sys.stderr)
            continue

        s3_key = f"fbar-pdfs/{tax_year}/FBAR_{bsa_id}.pdf"

        s3_client.upload_file(
            Filename=local_path,
            Bucket=bucket_name,
            Key=s3_key,
            ExtraArgs={"ContentType": "application/pdf"},
        )
        uploaded_count += 1

    return uploaded_count


def main():
    args = parse_args()

    try:
        s3_client = create_s3_client(args.endpoint_url)

        # Create bucket if it doesn't exist
        if not bucket_exists(s3_client, BUCKET_NAME):
            create_bucket(s3_client, BUCKET_NAME, args.endpoint_url)
        else:
            print(f"Bucket '{BUCKET_NAME}' already exists")

        # Load filings metadata to get bsaId -> taxYear mapping
        filings_path = os.path.abspath(FILINGS_JSON)
        if not os.path.isfile(filings_path):
            print(f"Error: Filings data not found: {filings_path}", file=sys.stderr)
            sys.exit(1)

        filings_metadata = load_filings_metadata(filings_path)

        # Verify PDFs directory exists
        pdfs_dir = os.path.abspath(PDFS_DIR)
        if not os.path.isdir(pdfs_dir):
            print(f"Error: PDFs directory not found: {pdfs_dir}", file=sys.stderr)
            sys.exit(1)

        # Upload PDFs
        uploaded_count = upload_pdfs(s3_client, BUCKET_NAME, filings_metadata, pdfs_dir)

        print(f"Successfully uploaded {uploaded_count} PDF files to s3://{BUCKET_NAME}/")

    except ClientError as e:
        print(f"Error: AWS operation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
