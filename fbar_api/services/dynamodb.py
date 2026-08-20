"""DynamoDB service client for FBAR filing data access."""

from datetime import datetime, timezone
from typing import Optional

import boto3
from boto3.dynamodb.conditions import Attr, Key

from fbar_api.config import Settings


class DynamoDBService:
    """Wrapper around DynamoDB operations for the fbar-filings table.

    Provides methods for getting, listing, querying, scanning, and updating
    filing records stored in DynamoDB.
    """

    RECORD_TYPE = "FILING"
    GSI_TAX_YEAR_STATUS = "GSI-TaxYearStatus"
    GSI_CASE_ID = "GSI-CaseId"

    def __init__(self, settings: Settings) -> None:
        """Initialize the DynamoDB service.

        Args:
            settings: Application settings containing table name and endpoint URL.
        """
        self._settings = settings
        self._table_name = settings.DYNAMODB_TABLE_NAME

        # Build boto3 resource kwargs with optional endpoint URL (for LocalStack)
        resource_kwargs: dict = {"service_name": "dynamodb", "region_name": settings.AWS_REGION}
        if settings.AWS_ENDPOINT_URL:
            resource_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL

        self._resource = boto3.resource(**resource_kwargs)
        self._table = self._resource.Table(self._table_name)

        # Low-level client for operations like describe_table
        client_kwargs: dict = {"service_name": "dynamodb", "region_name": settings.AWS_REGION}
        if settings.AWS_ENDPOINT_URL:
            client_kwargs["endpoint_url"] = settings.AWS_ENDPOINT_URL

        self._client = boto3.client(**client_kwargs)

    def get_filing(self, bsa_id: str) -> Optional[dict]:
        """Retrieve a single filing by its BSA ID.

        Args:
            bsa_id: The 14-digit BSA identifier.

        Returns:
            The filing record as a dict, or None if not found.
        """
        response = self._table.get_item(
            Key={"bsaId": bsa_id, "recordType": self.RECORD_TYPE}
        )
        return response.get("Item")

    def list_filings(self) -> list[dict]:
        """Scan all filing records from the table.

        Returns:
            List of all filing records.
        """
        items: list[dict] = []
        response = self._table.scan()
        items.extend(response.get("Items", []))

        # Handle pagination for large tables
        while "LastEvaluatedKey" in response:
            response = self._table.scan(
                ExclusiveStartKey=response["LastEvaluatedKey"]
            )
            items.extend(response.get("Items", []))

        return items

    def query_by_tax_year(self, year: int) -> list[dict]:
        """Query filings by tax year using GSI-TaxYearStatus.

        Args:
            year: The tax year to filter by.

        Returns:
            List of filing records matching the tax year.
        """
        items: list[dict] = []
        response = self._table.query(
            IndexName=self.GSI_TAX_YEAR_STATUS,
            KeyConditionExpression=Key("taxYear").eq(year),
        )
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                IndexName=self.GSI_TAX_YEAR_STATUS,
                KeyConditionExpression=Key("taxYear").eq(year),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return items

    def query_by_tax_year_and_status(self, year: int, status: str) -> list[dict]:
        """Query filings by tax year and filing status using GSI-TaxYearStatus.

        Args:
            year: The tax year to filter by (partition key).
            status: The filing status to filter by (sort key).

        Returns:
            List of filing records matching both tax year and status.
        """
        items: list[dict] = []
        response = self._table.query(
            IndexName=self.GSI_TAX_YEAR_STATUS,
            KeyConditionExpression=(
                Key("taxYear").eq(year) & Key("filingStatus").eq(status)
            ),
        )
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                IndexName=self.GSI_TAX_YEAR_STATUS,
                KeyConditionExpression=(
                    Key("taxYear").eq(year) & Key("filingStatus").eq(status)
                ),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return items

    def query_by_case_id(self, case_id: str) -> list[dict]:
        """Query filings by case ID using GSI-CaseId.

        Args:
            case_id: The case identifier to query for.

        Returns:
            List of filing records linked to the given case ID.
        """
        items: list[dict] = []
        response = self._table.query(
            IndexName=self.GSI_CASE_ID,
            KeyConditionExpression=Key("caseId").eq(case_id),
        )
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = self._table.query(
                IndexName=self.GSI_CASE_ID,
                KeyConditionExpression=Key("caseId").eq(case_id),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return items

    def scan_by_tin(self, tin: str) -> list[dict]:
        """Scan filings filtering by filer TIN value.

        Args:
            tin: The TIN value to match against filer.tin.value.

        Returns:
            List of filing records whose filer TIN matches.
        """
        items: list[dict] = []
        response = self._table.scan(
            FilterExpression=Attr("filer.tin.value").eq(tin)
        )
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = self._table.scan(
                FilterExpression=Attr("filer.tin.value").eq(tin),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return items

    def scan_by_status(self, status: str) -> list[dict]:
        """Scan filings filtering by filing status.

        Args:
            status: The filing status to filter by (e.g., "Accepted", "Rejected", "Pending").

        Returns:
            List of filing records with the matching filing status.
        """
        items: list[dict] = []
        response = self._table.scan(
            FilterExpression=Attr("filingStatus").eq(status)
        )
        items.extend(response.get("Items", []))

        # Handle pagination
        while "LastEvaluatedKey" in response:
            response = self._table.scan(
                FilterExpression=Attr("filingStatus").eq(status),
                ExclusiveStartKey=response["LastEvaluatedKey"],
            )
            items.extend(response.get("Items", []))

        return items

    def update_case_link(self, bsa_id: str, case_id: str) -> dict:
        """Update a filing to set its case link.

        Sets the caseId and updatedAt (ISO-8601 UTC) attributes on the filing.

        Args:
            bsa_id: The BSA ID of the filing to update.
            case_id: The case ID to link to the filing.

        Returns:
            The updated filing record.
        """
        now = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

        response = self._table.update_item(
            Key={"bsaId": bsa_id, "recordType": self.RECORD_TYPE},
            UpdateExpression="SET caseId = :cid, updatedAt = :ts",
            ExpressionAttributeValues={
                ":cid": case_id,
                ":ts": now,
            },
            ReturnValues="ALL_NEW",
        )
        return response.get("Attributes", {})

    def health_check(self) -> bool:
        """Check DynamoDB table availability.

        Performs a describe_table call with a 3-second timeout to verify
        the table is reachable and active.

        Returns:
            True if the table is reachable and active, False otherwise.
        """
        try:
            response = self._client.describe_table(
                TableName=self._table_name
            )
            return response["Table"]["TableStatus"] == "ACTIVE"
        except Exception:
            return False
