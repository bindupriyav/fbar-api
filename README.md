# FBAR API Service

A FastAPI-based REST API that serves FinCEN Form 114 (FBAR) filing data for the IRS Case Management Modernization platform.

## Features

- Paginated querying of FBAR filings with filtering by tax year, TIN, and filing status
- Single filing retrieval and financial account details
- PDF document access via presigned S3 URLs (302 redirect, 10-min TTL)
- Case-linking to associate filings with investigations
- Bearer token authentication, scope-based authorization (`fbar:read` / `fbar:write`)
- Row-level access control tied to case assignments
- Sliding window rate limiting (100 requests / 60 seconds per caller)
- Standard error envelopes with UUID trace IDs
- Health endpoint for load balancer probes

## Tech Stack

- Python 3.11, FastAPI, Uvicorn
- AWS DynamoDB (filing metadata), AWS S3 (PDF documents)
- Docker, AWS CodeBuild/ECR for CI/CD
- Deployed on ECS (Fargate)

---

## Quick Start — Local Development

### Prerequisites

- Python 3.11+
- Docker (for LocalStack)
- pip

### 1. Install dependencies

```bash
cd fbar-api
pip install -r requirements.txt
```

### 2. Run unit tests (no AWS needed)

```bash
pytest tests/unit/ -v
```

All 99 tests use moto to mock AWS — no real credentials required.

### 3. Run locally with LocalStack

```bash
# Start LocalStack
docker run -d --name localstack -p 4566:4566 localstack/localstack

# Load synthetic data
python scripts/load_dynamodb.py --endpoint-url http://localhost:4566
python scripts/load_s3.py --endpoint-url http://localhost:4566
```

Set environment variables (Windows CMD):
```cmd
set DYNAMODB_TABLE_NAME=fbar-filings
set S3_BUCKET_NAME=irs-cm-fbar-documents-dev
set AWS_ENDPOINT_URL=http://localhost:4566
set AUTH_TOKEN_STORE=tokens.json
set AWS_ACCESS_KEY_ID=test
set AWS_SECRET_ACCESS_KEY=test
set AWS_DEFAULT_REGION=us-east-1
```

Or PowerShell:
```powershell
$env:DYNAMODB_TABLE_NAME = "fbar-filings"
$env:S3_BUCKET_NAME = "irs-cm-fbar-documents-dev"
$env:AWS_ENDPOINT_URL = "http://localhost:4566"
$env:AUTH_TOKEN_STORE = "tokens.json"
$env:AWS_ACCESS_KEY_ID = "test"
$env:AWS_SECRET_ACCESS_KEY = "test"
$env:AWS_DEFAULT_REGION = "us-east-1"
```

Start the server:
```bash
uvicorn fbar_api.main:app --host 0.0.0.0 --port 8000 --reload
```

### 4. Test the API

```bash
# Health check (no auth required)
curl http://localhost:8000/health

# List filings (requires auth)
curl -H "Authorization: Bearer dev-token-read-only" http://localhost:8000/api/v1/fbar/filings

# Get single filing
curl -H "Authorization: Bearer dev-token-read-only" http://localhost:8000/api/v1/fbar/filings/31000000000001

# Get accounts for a filing
curl -H "Authorization: Bearer dev-token-read-only" http://localhost:8000/api/v1/fbar/filings/31000000000001/accounts

# Get PDF (returns 302 redirect to presigned URL)
curl -v -H "Authorization: Bearer dev-token-read-only" http://localhost:8000/api/v1/fbar/filings/31000000000001/pdf

# Link filing to a case (requires fbar:write scope)
curl -X POST -H "Authorization: Bearer dev-token-read-write" -H "Content-Type: application/json" -d "{\"caseId\": \"CASE-2024-001\"}" http://localhost:8000/api/v1/fbar/filings/31000000000001/case-link

# Filter by tax year
curl -H "Authorization: Bearer dev-token-read-only" "http://localhost:8000/api/v1/fbar/filings?taxYear=2023"

# Filter by status
curl -H "Authorization: Bearer dev-token-read-only" "http://localhost:8000/api/v1/fbar/filings?filingStatus=Accepted"

# Pagination
curl -H "Authorization: Bearer dev-token-read-only" "http://localhost:8000/api/v1/fbar/filings?page=1&pageSize=10"
```

### 5. Run with Docker locally

```bash
docker build -t fbar-api .

docker run -p 8000:8000 \
  -e DYNAMODB_TABLE_NAME=fbar-filings \
  -e S3_BUCKET_NAME=irs-cm-fbar-documents-dev \
  -e AWS_ENDPOINT_URL=http://host.docker.internal:4566 \
  -e AUTH_TOKEN_STORE=tokens.json \
  -e AWS_ACCESS_KEY_ID=test \
  -e AWS_SECRET_ACCESS_KEY=test \
  -e AWS_DEFAULT_REGION=us-east-1 \
  fbar-api
```

---

## Deploy to AWS — Step by Step

### Prerequisites

- AWS CLI configured (`aws configure`)
- Docker installed
- An AWS account with permissions for ECR, ECS, DynamoDB, S3, IAM, ALB

### Step 1: Create ECR Repository

```bash
aws ecr create-repository --repository-name fbar-api --region us-east-1
```

Note the `repositoryUri` from the output (e.g., `123456789012.dkr.ecr.us-east-1.amazonaws.com/fbar-api`).

### Step 2: Build and Push Docker Image

```bash
# Authenticate Docker with ECR
aws ecr get-login-password --region us-east-1 | docker login --username AWS --password-stdin 123456789012.dkr.ecr.us-east-1.amazonaws.com

# Build the image
docker build -t fbar-api .

# Tag it
docker tag fbar-api:latest 123456789012.dkr.ecr.us-east-1.amazonaws.com/fbar-api:latest

# Push to ECR
docker push 123456789012.dkr.ecr.us-east-1.amazonaws.com/fbar-api:latest
```

### Step 3: Create DynamoDB Table and Load Data

```bash
# Create table and load 50 synthetic filings (uses your default AWS credentials)
python scripts/load_dynamodb.py
```

This creates the `fbar-filings` table with:
- Partition key: `bsaId` (String)
- Sort key: `recordType` (String)
- GSI-TaxYearStatus: PK `taxYear` (Number), SK `filingStatus` (String)
- GSI-CaseId: PK `caseId` (String)

### Step 4: Create S3 Bucket and Upload PDFs

```bash
# Create bucket with encryption and upload 50 PDFs
python scripts/load_s3.py
```

This creates `irs-cm-fbar-documents-dev` with SSE-KMS encryption and block-public-access, then uploads PDFs using key pattern `fbar-pdfs/{taxYear}/FBAR_{bsaId}.pdf`.

### Step 5: Create IAM Task Role

Create a role `fbar-api-task-role` with these permissions:

```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Action": [
        "dynamodb:GetItem",
        "dynamodb:PutItem",
        "dynamodb:UpdateItem",
        "dynamodb:Query",
        "dynamodb:Scan",
        "dynamodb:DescribeTable"
      ],
      "Resource": [
        "arn:aws:dynamodb:us-east-1:*:table/fbar-filings",
        "arn:aws:dynamodb:us-east-1:*:table/fbar-filings/index/*"
      ]
    },
    {
      "Effect": "Allow",
      "Action": [
        "s3:GetObject",
        "s3:HeadObject",
        "s3:HeadBucket"
      ],
      "Resource": [
        "arn:aws:s3:::irs-cm-fbar-documents-dev",
        "arn:aws:s3:::irs-cm-fbar-documents-dev/*"
      ]
    }
  ]
}
```

The trust policy should allow ECS tasks to assume the role:
```json
{
  "Version": "2012-10-17",
  "Statement": [
    {
      "Effect": "Allow",
      "Principal": { "Service": "ecs-tasks.amazonaws.com" },
      "Action": "sts:AssumeRole"
    }
  ]
}
```

### Step 6: Create ECS Cluster

```bash
aws ecs create-cluster --cluster-name fbar-api-cluster --region us-east-1
```

### Step 7: Register ECS Task Definition

Create `task-definition.json`:
```json
{
  "family": "fbar-api",
  "networkMode": "awsvpc",
  "requiresCompatibilities": ["FARGATE"],
  "cpu": "256",
  "memory": "512",
  "taskRoleArn": "arn:aws:iam::123456789012:role/fbar-api-task-role",
  "executionRoleArn": "arn:aws:iam::123456789012:role/ecsTaskExecutionRole",
  "containerDefinitions": [
    {
      "name": "fbar-api",
      "image": "123456789012.dkr.ecr.us-east-1.amazonaws.com/fbar-api:latest",
      "portMappings": [
        { "containerPort": 8000, "protocol": "tcp" }
      ],
      "environment": [
        { "name": "DYNAMODB_TABLE_NAME", "value": "fbar-filings" },
        { "name": "S3_BUCKET_NAME", "value": "irs-cm-fbar-documents-dev" },
        { "name": "AUTH_TOKEN_STORE", "value": "tokens.json" },
        { "name": "AWS_DEFAULT_REGION", "value": "us-east-1" }
      ],
      "healthCheck": {
        "command": ["CMD-SHELL", "python -c \"import urllib.request; urllib.request.urlopen('http://localhost:8000/health')\" || exit 1"],
        "interval": 30,
        "timeout": 5,
        "retries": 3,
        "startPeriod": 10
      },
      "logConfiguration": {
        "logDriver": "awslogs",
        "options": {
          "awslogs-group": "/ecs/fbar-api",
          "awslogs-region": "us-east-1",
          "awslogs-stream-prefix": "ecs"
        }
      }
    }
  ]
}
```

Register it:
```bash
aws ecs register-task-definition --cli-input-json file://task-definition.json
```

### Step 8: Create ALB and Target Group

```bash
# Create Application Load Balancer (requires VPC subnet IDs)
aws elbv2 create-load-balancer \
  --name fbar-api-alb \
  --subnets subnet-xxxx subnet-yyyy \
  --security-groups sg-xxxx \
  --scheme internet-facing \
  --type application

# Create target group (IP type for Fargate awsvpc)
aws elbv2 create-target-group \
  --name fbar-api-tg \
  --protocol HTTP \
  --port 8000 \
  --vpc-id vpc-xxxx \
  --target-type ip \
  --health-check-path /health \
  --health-check-interval-seconds 30

# Create listener
aws elbv2 create-listener \
  --load-balancer-arn arn:aws:elasticloadbalancing:... \
  --protocol HTTP \
  --port 80 \
  --default-actions Type=forward,TargetGroupArn=arn:aws:elasticloadbalancing:...
```

### Step 9: Create ECS Service

```bash
aws ecs create-service \
  --cluster fbar-api-cluster \
  --service-name fbar-api-service \
  --task-definition fbar-api \
  --desired-count 1 \
  --launch-type FARGATE \
  --network-configuration "awsvpcConfiguration={subnets=[subnet-xxxx,subnet-yyyy],securityGroups=[sg-xxxx],assignPublicIp=ENABLED}" \
  --load-balancers "targetGroupArn=arn:aws:elasticloadbalancing:...,containerName=fbar-api,containerPort=8000"
```

### Step 10: Verify Deployment

```bash
# Get the ALB DNS name
aws elbv2 describe-load-balancers --names fbar-api-alb --query "LoadBalancers[0].DNSName" --output text

# Test health endpoint
curl http://<ALB-DNS>/health

# Test with auth
curl -H "Authorization: Bearer dev-token-read-only" http://<ALB-DNS>/api/v1/fbar/filings
```

---

## API Endpoints

| Method | Path | Scope | Description |
|--------|------|-------|-------------|
| GET | `/health` | None | Health check |
| GET | `/api/v1/fbar/filings` | fbar:read | List filings (paginated, filterable) |
| GET | `/api/v1/fbar/filings/{bsaId}` | fbar:read | Get single filing |
| GET | `/api/v1/fbar/filings/{bsaId}/accounts` | fbar:read | Get financial accounts |
| GET | `/api/v1/fbar/filings/{bsaId}/pdf` | fbar:read | Get PDF (302 redirect) |
| POST | `/api/v1/fbar/filings/{bsaId}/case-link` | fbar:write | Link filing to case |

## Query Parameters (List Filings)

| Param | Type | Default | Description |
|-------|------|---------|-------------|
| `page` | int | 1 | Page number (≥ 1) |
| `pageSize` | int | 25 | Items per page (1–100) |
| `taxYear` | int | — | Filter by tax year (2010–current) |
| `tin` | string | — | Filter by TIN (SSN: 900-xx-xxxx, EIN: 98-xxxxxxx) |
| `filingStatus` | string | — | Filter: Accepted, Rejected, or Pending |

## Authentication

All endpoints except `/health` require a Bearer token:

```
Authorization: Bearer dev-token-read-only
```

Available dev tokens (in `tokens.json`):
- `dev-token-read-only` — fbar:read scope, access to cases 001-003
- `dev-token-read-write` — fbar:read + fbar:write, access to cases 001-005

## Environment Variables

| Variable | Default | Description |
|----------|---------|-------------|
| `DYNAMODB_TABLE_NAME` | fbar-filings | DynamoDB table name |
| `S3_BUCKET_NAME` | irs-cm-fbar-documents-dev | S3 bucket for PDFs |
| `AWS_ENDPOINT_URL` | None | Custom endpoint (for LocalStack) |
| `AUTH_TOKEN_STORE` | tokens.json | Path to token store JSON |
| `RATE_LIMIT_MAX` | 100 | Max requests per window |
| `RATE_LIMIT_WINDOW_SECONDS` | 60 | Rate limit window in seconds |

## Project Structure

```
fbar-api/
├── fbar_api/                  # Application code
│   ├── main.py                # FastAPI app factory
│   ├── config.py              # Settings (env vars)
│   ├── models/                # Pydantic models
│   ├── routes/                # API route handlers
│   ├── auth/                  # Authentication & authorization
│   ├── middleware/            # Rate limiter, error handler
│   ├── services/              # DynamoDB & S3 clients
│   └── utils/                 # Pagination, validation
├── scripts/
│   ├── load_dynamodb.py       # Create table + load data
│   └── load_s3.py            # Create bucket + upload PDFs
├── tests/
│   ├── conftest.py            # Shared fixtures (moto mocks)
│   ├── unit/                  # 99 unit tests
│   └── properties/            # Property-based tests (hypothesis)
├── fbar_pdfs/pdfs/            # 50 synthetic PDF files
├── synthetic_fbar_filings.json # 50 synthetic filing records
├── tokens.json                # Dev token store
├── Dockerfile                 # Production container
├── buildspec.yml              # AWS CodeBuild CI/CD
└── requirements.txt           # Python dependencies
```
