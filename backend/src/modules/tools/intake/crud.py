"""FastCRUD instances for the Tool Requests tool."""

from fastcrud import FastCRUD

from .models import ToolRequest

crud_tool_requests: FastCRUD = FastCRUD(ToolRequest)
