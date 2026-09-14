"""FastCRUD instances for the Refunds tool."""

from fastcrud import FastCRUD

from .models import RefundRequest

crud_refund_requests: FastCRUD = FastCRUD(RefundRequest)
