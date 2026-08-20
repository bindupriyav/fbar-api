"""Shared test fixtures for the FBAR API Service test suite.

Provides:
- Mock DynamoDB table (moto) with correct schema (PK, SK, GSIs)
- Mock S3 bucket (moto) with test PDF objects
- Test token store with various CallerContext configurations
- Sample filing data representing common scenarios
- httpx AsyncClient fixture for FastAPI async testing
"""

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import AsyncGenerator

import boto3
import pytest
import pytest_asyncio
from httpx import ASGITransport, AsyncClient
from moto import mock_aws

from fbar_api.auth.bearer import CallerContext
from fbar_api.config import Settings
from fbar_api.main import create_app
from fbar_api.services.dynamodb import DynamoDBService
from fbar_api.services.s3 import S3Service


# ---------------------------------------------------------------------------
# AWS environment setup
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def aws_credentials():
    """Mock AWS credentials for moto."""
    os.environ["AWS_ACCESS_KEY_ID"] = "testing"
    os.environ["AWS_SECRET_ACCESS_KEY"] = "testing"
    os.environ["AWS_SECURITY_TOKEN"] = "testing"
    os.environ["AWS_SESSION_TOKEN"] = "testing"
    os.environ["AWS_DEFAULT_REGION"] = "us-east-1"
    yield
    # Cleanup is handled by moto context managers


# ---------------------------------------------------------------------------
# DynamoDB fixtures
# ---------------------------------------------------------------------------

DYNAMODB_TABLE_NAME = "fbar-filings"


@pytest.fixture
def dynamodb_table():
    """Create a mock DynamoDB table with the correct schema.

    Table: fbar-filings
    - PK: bsaId (S)
    - SK: recordType (S)
    - GSI-TaxYearStatus: PK=taxYear (N), SK=filingStatus (S)
    - GSI-CaseId: PK=caseId (S)
    """
    with mock_aws():
        client = boto3.client("dynamodb", region_name="us-east-1")
        client.create_table(
            TableName=DYNAMODB_TABLE_NAME,
            KeySchema=[
                {"AttributeName": "bsaId", "KeyType": "HASH"},
                {"AttributeName": "recordType", "KeyType": "RANGE"},
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
                    "IndexName": "GSI-TaxYearStatus",
                    "KeySchema": [
                        {"AttributeName": "taxYear", "KeyType": "HASH"},
                        {"AttributeName": "filingStatus", "KeyType": "RANGE"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
                {
                    "IndexName": "GSI-CaseId",
                    "KeySchema": [
                        {"AttributeName": "caseId", "KeyType": "HASH"},
                    ],
                    "Projection": {"ProjectionType": "ALL"},
                },
            ],
            BillingMode="PAY_PER_REQUEST",
        )

        # Return the table resource for direct item manipulation
        resource = boto3.resource("dynamodb", region_name="us-east-1")
        table = resource.Table(DYNAMODB_TABLE_NAME)
        yield table


# ---------------------------------------------------------------------------
# S3 fixtures
# ---------------------------------------------------------------------------

S3_BUCKET_NAME = "irs-cm-fbar-documents-dev"


@pytest.fixture
def s3_bucket():
    """Create a mock S3 bucket with the correct name."""
    with mock_aws():
        client = boto3.client("s3", region_name="us-east-1")
        client.create_bucket(Bucket=S3_BUCKET_NAME)
        yield client


# ---------------------------------------------------------------------------
# Token store and CallerContext fixtures
# ---------------------------------------------------------------------------

# Future expiry for test tokens
_TOKEN_EXPIRY = (datetime.now(timezone.utc) + timedelta(days=365)).isoformat()

# Expired token expiry
_EXPIRED_TOKEN_EXPIRY = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()

# Test token definitions
TEST_TOKENS = {
    "test-read-token": {
        "subject": "analyst-test",
        "scopes": ["fbar:read"],
        "case_ids": ["CASE-001", "CASE-002", "CASE-003"],
        "expires_at": _TOKEN_EXPIRY,
    },
    "test-write-token": {
        "subject": "supervisor-test",
        "scopes": ["fbar:read", "fbar:write"],
        "case_ids": ["CASE-001", "CASE-002", "CASE-003", "CASE-004", "CASE-005"],
        "expires_at": _TOKEN_EXPIRY,
    },
    "test-read-only-no-write": {
        "subject": "readonly-user",
        "scopes": ["fbar:read"],
        "case_ids": ["CASE-001"],
        "expires_at": _TOKEN_EXPIRY,
    },
    "test-no-scopes-token": {
        "subject": "no-scopes-user",
        "scopes": [],
        "case_ids": ["CASE-001"],
        "expires_at": _TOKEN_EXPIRY,
    },
    "test-no-cases-token": {
        "subject": "no-cases-user",
        "scopes": ["fbar:read", "fbar:write"],
        "case_ids": [],
        "expires_at": _TOKEN_EXPIRY,
    },
    "test-expired-token": {
        "subject": "expired-user",
        "scopes": ["fbar:read"],
        "case_ids": ["CASE-001"],
        "expires_at": _EXPIRED_TOKEN_EXPIRY,
    },
}


@pytest.fixture
def token_store_path() -> str:
    """Create a temporary token store file and return its path."""
    tmp = tempfile.NamedTemporaryFile(
        mode="w", suffix=".json", delete=False, prefix="test_tokens_"
    )
    json.dump(TEST_TOKENS, tmp)
    tmp.close()
    return tmp.name


# Pre-built CallerContext instances for common test scenarios
@pytest.fixture
def caller_read() -> CallerContext:
    """CallerContext with fbar:read scope and access to CASE-001..003."""
    return CallerContext(
        subject="analyst-test",
        scopes={"fbar:read"},
        case_ids=["CASE-001", "CASE-002", "CASE-003"],
    )


@pytest.fixture
def caller_write() -> CallerContext:
    """CallerContext with fbar:read + fbar:write scopes and access to CASE-001..005."""
    return CallerContext(
        subject="supervisor-test",
        scopes={"fbar:read", "fbar:write"},
        case_ids=["CASE-001", "CASE-002", "CASE-003", "CASE-004", "CASE-005"],
    )


@pytest.fixture
def caller_no_scopes() -> CallerContext:
    """CallerContext with no scopes (should be denied all access)."""
    return CallerContext(
        subject="no-scopes-user",
        scopes=set(),
        case_ids=["CASE-001"],
    )


@pytest.fixture
def caller_no_cases() -> CallerContext:
    """CallerContext with scopes but empty case_ids (only unlinked filings accessible)."""
    return CallerContext(
        subject="no-cases-user",
        scopes={"fbar:read", "fbar:write"},
        case_ids=[],
    )


# ---------------------------------------------------------------------------
# Sample filing data
# ---------------------------------------------------------------------------


@pytest.fixture
def sample_filing() -> dict:
    """A single complete filing record for testing."""
    return {
        "bsaId": "31000000000001",
        "recordType": "FILING",
        "submissionType": "Original",
        "filingStatus": "Accepted",
        "taxYear": 2023,
        "dateFiled": "2024-05-07",
        "priorReportBsaId": None,
        "filer": {
            "filerType": "Individual",
            "usPersonCategory": "Resident Alien",
            "tin": {"type": "SSN", "value": "900-51-1424"},
            "name": {"last": "Kowalski", "first": "Chidi", "middle": "E"},
            "address": {
                "street": "666 Fieldstone Ave",
                "city": "Plano",
                "stateOrProvince": "TX",
                "zipOrPostal": "44507",
                "country": "US",
            },
            "dateOfBirth": "1958-07-04",
            "occupation": "Small Business Owner",
        },
        "jointFilers": [],
        "financialAccounts": [
            {
                "accountNumber": "TEST-ACCT-0001-A",
                "accountType": "Bank",
                "currency": "CAD",
                "financialInstitution": {
                    "name": "Northern Shore Credit Union",
                    "address": {"city": "Halifax", "country": "CA"},
                },
                "jointOwnerCount": 0,
                "accountClosedDuringYear": False,
                "maxAccountValueUSD": 475283.85,
            }
        ],
        "signature": {
            "signed": True,
            "signatureDate": "2024-05-07",
            "preparerUsed": False,
        },
        "pdfDocument": {
            "fileName": "FBAR_31000000000001.pdf",
            "s3Bucket": "irs-cm-fbar-documents-dev",
            "s3Key": "fbar-pdfs/2023/FBAR_31000000000001.pdf",
            "contentType": "application/pdf",
            "sizeBytes": 4256,
            "sha256": "5b9303f113cc332c455e20ad1abbc74210b46fc7626cf2926d526bbcd667e214",
        },
    }


@pytest.fixture
def sample_filings() -> list[dict]:
    """A collection of filings with varying attributes for testing filters and pagination.

    Includes:
    - Different tax years (2021, 2022, 2023)
    - Different statuses (Accepted, Rejected, Pending)
    - Different TINs (SSN and EIN formats)
    - Some with caseId (for row-level access testing), some without
    - Varying number of financial accounts (0, 1, 2)
    """
    return [
        {
            "bsaId": "31000000000001",
            "recordType": "FILING",
            "submissionType": "Original",
            "filingStatus": "Accepted",
            "taxYear": 2023,
            "dateFiled": "2024-05-07",
            "filer": {
                "filerType": "Individual",
                "usPersonCategory": "Resident Alien",
                "tin": {"type": "SSN", "value": "900-51-1424"},
                "name": {"last": "Kowalski", "first": "Chidi", "middle": "E"},
                "address": {
                    "street": "666 Fieldstone Ave",
                    "city": "Plano",
                    "stateOrProvince": "TX",
                    "zipOrPostal": "44507",
                    "country": "US",
                },
            },
            "jointFilers": [],
            "financialAccounts": [
                {
                    "accountNumber": "TEST-ACCT-0001-A",
                    "accountType": "Bank",
                    "currency": "CAD",
                    "financialInstitution": {
                        "name": "Northern Shore Credit Union",
                        "address": {"city": "Halifax", "country": "CA"},
                    },
                    "jointOwnerCount": 0,
                    "accountClosedDuringYear": False,
                    "maxAccountValueUSD": 475283.85,
                }
            ],
            "signature": {"signed": True, "signatureDate": "2024-05-07", "preparerUsed": False},
            "pdfDocument": {
                "fileName": "FBAR_31000000000001.pdf",
                "s3Bucket": "irs-cm-fbar-documents-dev",
                "s3Key": "fbar-pdfs/2023/FBAR_31000000000001.pdf",
                "contentType": "application/pdf",
                "sizeBytes": 4256,
                "sha256": "abc123",
            },
        },
        {
            "bsaId": "31000000000002",
            "recordType": "FILING",
            "submissionType": "Original",
            "filingStatus": "Pending",
            "taxYear": 2023,
            "dateFiled": "2024-07-13",
            "filer": {
                "filerType": "Entity",
                "usPersonCategory": "Domestic Entity",
                "tin": {"type": "EIN", "value": "98-7654321"},
                "name": {"entityName": "TestCorp LLC"},
                "address": {
                    "street": "100 Main St",
                    "city": "New York",
                    "stateOrProvince": "NY",
                    "zipOrPostal": "10001",
                    "country": "US",
                },
            },
            "jointFilers": [],
            "financialAccounts": [
                {
                    "accountNumber": "TEST-ACCT-0002-A",
                    "accountType": "Securities",
                    "currency": "USD",
                    "financialInstitution": {
                        "name": "Swiss Global Bank",
                        "address": {"city": "Zurich", "country": "CH"},
                    },
                    "jointOwnerCount": 1,
                    "accountClosedDuringYear": False,
                    "maxAccountValueUSD": 1250000.00,
                },
                {
                    "accountNumber": "TEST-ACCT-0002-B",
                    "accountType": "Bank",
                    "currency": "EUR",
                    "financialInstitution": {
                        "name": "Deutsche Kredit AG",
                        "address": {"city": "Frankfurt", "country": "DE"},
                    },
                    "jointOwnerCount": 0,
                    "accountClosedDuringYear": True,
                    "maxAccountValueUSD": 89500.00,
                },
            ],
            "signature": {"signed": True, "signatureDate": "2024-07-13", "preparerUsed": True, "preparerPtin": "P12345678"},
            "pdfDocument": {
                "fileName": "FBAR_31000000000002.pdf",
                "s3Bucket": "irs-cm-fbar-documents-dev",
                "s3Key": "fbar-pdfs/2023/FBAR_31000000000002.pdf",
                "contentType": "application/pdf",
                "sizeBytes": 5120,
                "sha256": "def456",
            },
            "caseId": "CASE-001",
        },
        {
            "bsaId": "31000000000003",
            "recordType": "FILING",
            "submissionType": "Amended",
            "filingStatus": "Rejected",
            "taxYear": 2022,
            "dateFiled": "2023-10-15",
            "priorReportBsaId": "31000000000099",
            "filer": {
                "filerType": "Individual",
                "usPersonCategory": "Citizen",
                "tin": {"type": "SSN", "value": "900-99-8888"},
                "name": {"last": "Thompson", "first": "Alice"},
                "address": {
                    "street": "42 Oak Lane",
                    "city": "Chicago",
                    "stateOrProvince": "IL",
                    "zipOrPostal": "60601",
                    "country": "US",
                },
            },
            "jointFilers": [],
            "financialAccounts": [],
            "signature": {"signed": True, "signatureDate": "2023-10-15", "preparerUsed": False},
            "pdfDocument": {
                "fileName": "FBAR_31000000000003.pdf",
                "s3Bucket": "irs-cm-fbar-documents-dev",
                "s3Key": "fbar-pdfs/2022/FBAR_31000000000003.pdf",
                "contentType": "application/pdf",
                "sizeBytes": 3800,
                "sha256": "ghi789",
            },
        },
        {
            "bsaId": "31000000000004",
            "recordType": "FILING",
            "submissionType": "Original",
            "filingStatus": "Accepted",
            "taxYear": 2022,
            "dateFiled": "2023-04-10",
            "filer": {
                "filerType": "Individual",
                "usPersonCategory": "Citizen",
                "tin": {"type": "SSN", "value": "900-55-4321"},
                "name": {"last": "Garcia", "first": "Maria", "middle": "L"},
                "address": {
                    "street": "789 Elm Street",
                    "city": "Miami",
                    "stateOrProvince": "FL",
                    "zipOrPostal": "33101",
                    "country": "US",
                },
            },
            "jointFilers": [],
            "financialAccounts": [
                {
                    "accountNumber": "TEST-ACCT-0004-A",
                    "accountType": "Bank",
                    "currency": "GBP",
                    "financialInstitution": {
                        "name": "Barclays UK",
                        "address": {"city": "London", "country": "GB"},
                    },
                    "jointOwnerCount": 0,
                    "accountClosedDuringYear": False,
                    "maxAccountValueUSD": 320000.00,
                }
            ],
            "signature": {"signed": True, "signatureDate": "2023-04-10", "preparerUsed": False},
            "pdfDocument": None,
            "caseId": "CASE-999",
        },
        {
            "bsaId": "31000000000005",
            "recordType": "FILING",
            "submissionType": "Original",
            "filingStatus": "Accepted",
            "taxYear": 2021,
            "dateFiled": "2022-06-15",
            "filer": {
                "filerType": "Individual",
                "usPersonCategory": "Citizen",
                "tin": {"type": "SSN", "value": "900-51-1424"},
                "name": {"last": "Kowalski", "first": "Chidi", "middle": "E"},
                "address": {
                    "street": "666 Fieldstone Ave",
                    "city": "Plano",
                    "stateOrProvince": "TX",
                    "zipOrPostal": "44507",
                    "country": "US",
                },
            },
            "jointFilers": [],
            "financialAccounts": [
                {
                    "accountNumber": "TEST-ACCT-0005-A",
                    "accountType": "Bank",
                    "currency": "JPY",
                    "financialInstitution": {
                        "name": "Mizuho Bank",
                        "address": {"city": "Tokyo", "country": "JP"},
                    },
                    "jointOwnerCount": 2,
                    "accountClosedDuringYear": False,
                    "maxAccountValueUSD": 150000.00,
                }
            ],
            "signature": {"signed": True, "signatureDate": "2022-06-15", "preparerUsed": False},
            "pdfDocument": {
                "fileName": "FBAR_31000000000005.pdf",
                "s3Bucket": "irs-cm-fbar-documents-dev",
                "s3Key": "fbar-pdfs/2021/FBAR_31000000000005.pdf",
                "contentType": "application/pdf",
                "sizeBytes": 4100,
                "sha256": "jkl012",
            },
            "caseId": "CASE-002",
        },
    ]


# ---------------------------------------------------------------------------
# Application and client fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def test_settings(token_store_path: str) -> Settings:
    """Create test Settings pointing to mock resources."""
    return Settings(
        DYNAMODB_TABLE_NAME=DYNAMODB_TABLE_NAME,
        S3_BUCKET_NAME=S3_BUCKET_NAME,
        AWS_ENDPOINT_URL=None,  # moto intercepts boto3 calls directly
        AUTH_TOKEN_STORE=token_store_path,
        RATE_LIMIT_MAX=100,
        RATE_LIMIT_WINDOW_SECONDS=60,
    )


@pytest.fixture
def app(test_settings: Settings):
    """Create a FastAPI app with test settings.

    Note: For tests using moto mock_aws, wrap the test function
    with the @mock_aws decorator or use the dynamodb_table/s3_bucket
    fixtures which handle the mock context.
    """
    return create_app(test_settings)


@pytest_asyncio.fixture
async def async_client(app) -> AsyncGenerator[AsyncClient, None]:
    """Create an httpx AsyncClient for async testing of the FastAPI app.

    Usage:
        async def test_something(async_client):
            response = await async_client.get("/health")
            assert response.status_code == 200
    """
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as client:
        yield client


# ---------------------------------------------------------------------------
# Auth header helpers
# ---------------------------------------------------------------------------


@pytest.fixture
def auth_headers_read() -> dict[str, str]:
    """Authorization headers with a read-only token."""
    return {"Authorization": "Bearer test-read-token"}


@pytest.fixture
def auth_headers_write() -> dict[str, str]:
    """Authorization headers with a read+write token."""
    return {"Authorization": "Bearer test-write-token"}


@pytest.fixture
def auth_headers_no_scopes() -> dict[str, str]:
    """Authorization headers with a token that has no scopes."""
    return {"Authorization": "Bearer test-no-scopes-token"}


@pytest.fixture
def auth_headers_no_cases() -> dict[str, str]:
    """Authorization headers with a token that has empty case_ids."""
    return {"Authorization": "Bearer test-no-cases-token"}


@pytest.fixture
def auth_headers_expired() -> dict[str, str]:
    """Authorization headers with an expired token."""
    return {"Authorization": "Bearer test-expired-token"}
