#!/usr/bin/env python3
"""
Load synthetic FBAR filings into a DynamoDB table.

Creates the fbar-filings table (with GSIs) if it does not exist,
waits for the table to become ACTIVE, then loads all 50 records from
synthetic_fbar_filings.json using put_item (overwrite on conflict).

Usage:
    python scripts/load_dynamodb.py
    python scripts/load_dynamodb.py --endpoint-url http://localhost:4566
"""

import argparse
import json
import sys
import time
from decimal import Decimal
from pathlib import Path

import boto3
from botocore.exceptions import BotoCoreError, ClientError

TABLE_NAME = "fbar-filings"
DATA_FILE = Path(__file__).resolve().parent.parent / "synthetic_fbar_filings.json"

# Table schema constants
PARTITION_KEY = "bsaId"
SORT_KEY = "recordType"
GSI_TAX_YEAR_STATUS = "GSI-TaxYearStatus"
GSI_CASE_ID = "GSI-CaseId"


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Load synthetic FBAR filings into DynamoDB"
    )
    parser.add_argument(
        "--endpoint-url",
        type=str,
        default=None,
        help="Custom endpoint URL (e.g., http://localhost:4566 for LocalStack)",
    )
    return parser.parse_args()


def get_dynamodb_resource(endpoint_url: str | None = None):
    """Create a boto3 DynamoDB resource with optional endpoint override."""
    kwargs = {}
    if endpoint_url:
        kwargs["endpoint_url"] = endpoint_url
    return boto3.resource("dynamodb", **kwargs)


def table_exists(dynamodb_resource, table_name: str) -> bool:
    """Check if a DynamoDB table already exists."""
    try:
        table = dynamodb_resource.Table(table_name)
        table.load()
        return True
    except ClientError as e:
        if e.response["Error"]["Code"] == "ResourceNotFoundException":
            return False
        raise


def create_table(dynamodb_resource, table_name: str):
    """Create the fbar-filings table with required schema and GSIs."""
    table = dynamodb_resource.create_table(
        TableName=table_name,
        KeySchema=[
            {"AttributeName": PARTITION_KEY, "KeyType": "HASH"},
            {"AttributeName": SORT_KEY, "KeyType": "RANGE"},
        ],
        AttributeDefinitions=[
            {"AttributeName": "bsaId", "AttributeType": "S"},
            {"AttributeName": "recordType", "AttributeType": "S"},
            {"AttributeName": "taxYear", "AttributeType": "N"},
            {"AttributeName": "filingStatus", "AttributeType": "S"},
            {"AttributeName": "caseId", "AttributeType": "S"},
        ],
        GlobalSecondaryIndexes=[
            {
                "IndexName": GSI_TAX_YEAR_STATUS,
                "KeySchema": [
                    {"AttributeName": "taxYear", "KeyType": "HASH"},
                    {"AttributeName": "filingStatus", "KeyType": "RANGE"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 5,
                    "WriteCapacityUnits": 5,
                },
            },
            {
                "IndexName": GSI_CASE_ID,
                "KeySchema": [
                    {"AttributeName": "caseId", "KeyType": "HASH"},
                ],
                "Projection": {"ProjectionType": "ALL"},
                "ProvisionedThroughput": {
                    "ReadCapacityUnits": 5,
                    "WriteCapacityUnits": 5,
                },
            },
        ],
        ProvisionedThroughput={
            "ReadCapacityUnits": 5,
            "WriteCapacityUnits": 5,
        },
    )
    return table


def wait_for_table_active(dynamodb_resource, table_name: str, timeout: int = 60):
    """Wait until the table status is ACTIVE."""
    table = dynamodb_resource.Table(table_name)
    start = time.time()
    while True:
        table.reload()
        status = table.table_status
        if status == "ACTIVE":
            return
        if time.time() - start > timeout:
            raise TimeoutError(
                f"Table '{table_name}' did not become ACTIVE within {timeout}s "
                f"(current status: {status})"
            )
        time.sleep(1)


def load_data(dynamodb_resource, table_name: str, filings: list[dict]) -> int:
    """Load filing records into the table using batch_writer (overwrite on conflict)."""
    table = dynamodb_resource.Table(table_name)
    count = 0

    with table.batch_writer(overwrite_by_pkeys=[PARTITION_KEY, SORT_KEY]) as batch:
        for filing in filings:
            item = build_item(filing)
            batch.put_item(Item=item)
            count += 1

    return count


def convert_floats_to_decimal(obj):
    """Recursively convert float values to Decimal for DynamoDB compatibility."""
    if isinstance(obj, float):
        return Decimal(str(obj))
    elif isinstance(obj, dict):
        return {k: convert_floats_to_decimal(v) for k, v in obj.items()}
    elif isinstance(obj, list):
        return [convert_floats_to_decimal(item) for item in obj]
    return obj


def build_item(filing: dict) -> dict:
    """Convert a filing JSON record into a DynamoDB item with recordType sort key."""
    item = {
        "bsaId": filing["bsaId"],
        "recordType": "FILING",
        "submissionType": filing.get("submissionType"),
        "filingStatus": filing["filingStatus"],
        "taxYear": filing["taxYear"],
        "dateFiled": filing.get("dateFiled"),
        "filer": filing.get("filer"),
        "jointFilers": filing.get("jointFilers", []),
        "financialAccounts": filing.get("financialAccounts", []),
        "signature": filing.get("signature"),
    }

    # Optional fields
    if filing.get("priorReportBsaId"):
        item["priorReportBsaId"] = filing["priorReportBsaId"]
    if filing.get("pdfDocument"):
        item["pdfDocument"] = filing["pdfDocument"]
    if filing.get("caseId"):
        item["caseId"] = filing["caseId"]
    if filing.get("updatedAt"):
        item["updatedAt"] = filing["updatedAt"]

    # Remove None values (DynamoDB doesn't accept None for non-existent attributes)
    item = {k: v for k, v in item.items() if v is not None}

    # Convert floats to Decimal (DynamoDB requires Decimal for numeric types)
    item = convert_floats_to_decimal(item)

    return item


def main():
    args = parse_args()

    # Load the synthetic data file
    if not DATA_FILE.exists():
        print(f"Error: Data file not found: {DATA_FILE}", file=sys.stderr)
        sys.exit(1)

    try:
        with open(DATA_FILE, "r", encoding="utf-8") as f:
            data = json.load(f)
    except (json.JSONDecodeError, OSError) as e:
        print(f"Error: Failed to read data file: {e}", file=sys.stderr)
        sys.exit(1)

    filings = data.get("filings", [])
    if not filings:
        print("Error: No filings found in data file", file=sys.stderr)
        sys.exit(1)

    try:
        dynamodb = get_dynamodb_resource(args.endpoint_url)

        # Create table if it doesn't exist
        if not table_exists(dynamodb, TABLE_NAME):
            print(f"Creating table '{TABLE_NAME}'...")
            create_table(dynamodb, TABLE_NAME)
            print(f"Waiting for table '{TABLE_NAME}' to become ACTIVE...")
            wait_for_table_active(dynamodb, TABLE_NAME)
            print(f"Table '{TABLE_NAME}' is ACTIVE.")
        else:
            print(f"Table '{TABLE_NAME}' already exists.")

        # Load records
        print(f"Loading {len(filings)} records into '{TABLE_NAME}'...")
        records_written = load_data(dynamodb, TABLE_NAME, filings)
        print(f"Successfully loaded {records_written} records into '{TABLE_NAME}'.")

    except (BotoCoreError, ClientError) as e:
        print(f"Error: AWS operation failed: {e}", file=sys.stderr)
        sys.exit(1)
    except TimeoutError as e:
        print(f"Error: {e}", file=sys.stderr)
        sys.exit(1)
    except Exception as e:
        print(f"Error: Unexpected failure: {e}", file=sys.stderr)
        sys.exit(1)


if __name__ == "__main__":
    main()
