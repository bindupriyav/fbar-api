"""Pydantic models for FBAR filing data structures."""

from typing import Literal, Optional

from pydantic import BaseModel


class TIN(BaseModel):
    """Taxpayer Identification Number (SSN or EIN)."""

    type: Literal["SSN", "EIN"]
    value: str


class FilerName(BaseModel):
    """Name fields for a filer (individual or entity)."""

    last: Optional[str] = None
    first: Optional[str] = None
    middle: Optional[str] = None
    entityName: Optional[str] = None


class Address(BaseModel):
    """Mailing or physical address."""

    street: str
    city: str
    stateOrProvince: Optional[str] = None
    zipOrPostal: str
    country: str


class Filer(BaseModel):
    """Primary filer on an FBAR filing."""

    filerType: Literal["Individual", "Entity"]
    usPersonCategory: str
    tin: TIN
    name: FilerName
    address: Address
    dateOfBirth: Optional[str] = None
    occupation: Optional[str] = None
    entityType: Optional[str] = None


class JointFiler(BaseModel):
    """Joint filer associated with an FBAR filing."""

    name: FilerName
    tin: TIN
    relationship: str


class FinancialInstitution(BaseModel):
    """Foreign financial institution holding an account."""

    name: str
    address: Address


class FinancialAccount(BaseModel):
    """Foreign financial account reported on an FBAR filing."""

    accountNumber: str
    accountType: str
    currency: str
    financialInstitution: FinancialInstitution
    jointOwnerCount: int
    accountClosedDuringYear: bool
    maxAccountValueUSD: Optional[float] = None


class Signature(BaseModel):
    """Signature block for an FBAR filing."""

    signed: bool
    signatureDate: Optional[str] = None
    preparerUsed: bool
    preparerPtin: Optional[str] = None


class PdfDocument(BaseModel):
    """Reference to a PDF document stored in S3."""

    fileName: str
    s3Bucket: str
    s3Key: str
    contentType: str
    sizeBytes: int
    sha256: str


class Filing(BaseModel):
    """Complete FBAR filing record (FinCEN Form 114)."""

    bsaId: str
    submissionType: str
    filingStatus: Literal["Accepted", "Rejected", "Pending"]
    taxYear: int
    dateFiled: str
    priorReportBsaId: Optional[str] = None
    filer: Filer
    jointFilers: list[JointFiler] = []
    financialAccounts: list[FinancialAccount] = []
    signature: Signature
    pdfDocument: Optional[PdfDocument] = None
    caseId: Optional[str] = None
    updatedAt: Optional[str] = None
