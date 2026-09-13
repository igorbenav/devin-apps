"""FastCRUD instances for the Feature Flags tool."""

from fastcrud import FastCRUD

from .models import Flag

crud_flags: FastCRUD = FastCRUD(Flag)
