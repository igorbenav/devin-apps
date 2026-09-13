"""FastCRUD instances for the KYC Review Queue tool."""

from fastcrud import FastCRUD

from .models import KycCase, KycDocument

crud_kyc_cases: FastCRUD = FastCRUD(KycCase)
crud_kyc_documents: FastCRUD = FastCRUD(KycDocument)
