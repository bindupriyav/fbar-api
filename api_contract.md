# Mock FBAR Filing API — Contract (for test-harness use)

This describes a **synthetic** REST API surface, backed by `synthetic_fbar_filings.json`,
that the case-management app can call against during integration testing. Nothing here
represents an actual FinCEN/BSA E-Filing endpoint or credential — it's a stand-in your
test harness (e.g. WireMock, Prism, json-server, or a small Express/Flask stub) can
implement so downstream workflows can be exercised without touching production BSA data.

## Base

```
GET  /api/v1/fbar/filings
GET  /api/v1/fbar/filings/{bsaId}
GET  /api/v1/fbar/filings?taxYear={yyyy}
GET  /api/v1/fbar/filings?tin={tin}
GET  /api/v1/fbar/filings?filingStatus={status}
GET  /api/v1/fbar/filings/{bsaId}/accounts
GET  /api/v1/fbar/filings/{bsaId}/pdf         (streams/redirects to the filing's specimen PDF)
POST /api/v1/fbar/filings/{bsaId}/case-link   (associates a filing to a case ID)
```

## Auth (simulate, don't build real IAM here)

- `Authorization: Bearer <token>` — required on all routes.
- Missing/expired token → `401` with `{"error":"unauthorized"}`.
- Valid token but caller's role lacks `fbar:read` scope → `403` with `{"error":"forbidden","requiredScope":"fbar:read"}`.
- Token valid but case-context doesn't match filing's assigned case (row-level authz) → `403`.

## Pagination

`?page=1&pageSize=25`, response envelope:
```json
{ "data": [ ... ], "page": 1, "pageSize": 25, "totalRecords": 50, "totalPages": 2 }
```

## Standard error envelope

```json
{ "error": "string_code", "message": "human readable", "traceId": "uuid" }
```

## Storage backing this contract

In the prototype, `GET /filings*` routes read from **DynamoDB** (the JSON filing
records), and `GET /filings/{bsaId}/pdf` reads the PDF bytes from **S3**, using the
`pdfDocument` pointer stored on the DynamoDB item. See `dynamodb_schema.md` for the
table/GSI design and why the PDF itself isn't stored inline in DynamoDB.

## Status codes to implement in the stub

| Code | Meaning |
|---|---|
| 200 | success |
| 400 | malformed query param (e.g. non-numeric taxYear) |
| 401 | missing/invalid auth |
| 403 | authenticated but not authorized for this record/scope |
| 404 | bsaId not found |
| 409 | case-link conflict (already linked to a different case) |
| 422 | semantically invalid filter (e.g. taxYear out of supported range) |
| 429 | rate limited |
| 500 / 503 | simulated upstream (BSA system) failure, for resiliency testing |
