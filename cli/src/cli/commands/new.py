"""``bp new`` — scaffold new pieces of the application.

Today the only subcommand is ``bp new tool``, which writes a complete
vertical-slice internal tool under ``backend/src/modules/tools/<slug>/``:
model, schemas, FastCRUD, service (with an audit call), router, templates,
SQLAdmin view, ToolSpec, and unit tests. The generated tool registers itself
with the platform on import, so no shared file needs editing.

Two steps stay manual on purpose, and are printed at the end: the Alembic
migration (autogenerate then review) and adding the new permission to the
seeded roles.
"""

from __future__ import annotations

import re
from pathlib import Path
from typing import Any

import typer
from jinja2 import Environment, FileSystemLoader, StrictUndefined

from ..lib.project import discover_project
from ..lib.prompts import error, info

app = typer.Typer(no_args_is_help=True, help="Scaffold new application code.")

TEMPLATES_ROOT = Path(__file__).parent / "templates" / "tool"

SLUG_PATTERN = re.compile(r"^[a-z][a-z0-9_]*$")
PERMISSION_PATTERN = re.compile(r"^[a-z][a-z0-9_]*(\.[a-z][a-z0-9_]*)+$")


def _pascal_case(slug: str) -> str:
    return "".join(part.capitalize() for part in slug.split("_"))


def _environment() -> Environment:
    """Jinja with ``<< >>`` delimiters so templates can emit Jinja (and Python lists) of their own."""
    return Environment(
        loader=FileSystemLoader(str(TEMPLATES_ROOT)),
        variable_start_string="<<",
        variable_end_string=">>",
        block_start_string="<%",
        block_end_string="%>",
        comment_start_string="<#",
        comment_end_string="#>",
        keep_trailing_newline=True,
        undefined=StrictUndefined,
        autoescape=False,
    )


@app.command("tool")
def new_tool(
    slug: str = typer.Argument(..., help="Module name, snake_case, e.g. `kyc_review`."),
    label: str = typer.Option(..., "--label", help='Human label shown in the nav and launcher, e.g. "KYC Review".'),
    permission: str = typer.Option(..., "--permission", help="Permission required to open the tool, e.g. `kyc.review`."),
    description: str = typer.Option("", "--description", help="One line shown on the launcher card."),
    force: bool = typer.Option(False, "--force", "-f", help="Overwrite existing files."),
    dry_run: bool = typer.Option(False, "--dry-run", help="Show what would be written, don't touch disk."),
) -> None:
    """Generate a new internal tool module."""
    if not SLUG_PATTERN.match(slug):
        error(f"Invalid slug {slug!r}: use lowercase letters, digits and underscores, starting with a letter.")
        raise typer.Exit(code=1)
    if not PERMISSION_PATTERN.match(permission):
        error(f"Invalid permission {permission!r}: use a dotted lowercase string such as 'kyc.review'.")
        raise typer.Exit(code=1)

    project = discover_project()
    module_dir = project.backend_dir / "src" / "modules" / "tools" / slug
    test_file = project.backend_dir / "tests" / "unit" / "tools" / f"test_{slug}.py"

    context: dict[str, Any] = {
        "slug": slug,
        "label": label,
        "permission": permission,
        "description": description or f"{label} internal tool.",
        "class_prefix": _pascal_case(slug),
        "const_prefix": slug.upper(),
    }

    targets: dict[Path, str] = {
        module_dir / "__init__.py": "module__init__.py.j2",
        module_dir / "models.py": "models.py.j2",
        module_dir / "schemas.py": "schemas.py.j2",
        module_dir / "crud.py": "crud.py.j2",
        module_dir / "service.py": "service.py.j2",
        module_dir / "router.py": "router.py.j2",
        module_dir / "admin.py": "admin.py.j2",
        module_dir / "tool.py": "tool.py.j2",
        module_dir / "templates" / slug / "list.html": "list.html.j2",
        module_dir / "templates" / slug / "detail.html": "detail.html.j2",
        module_dir / "templates" / slug / "_row.html": "_row.html.j2",
        test_file: "test_tool.py.j2",
    }

    existing = [path for path in targets if path.exists()]
    if existing and not force:
        error(f"Refusing to overwrite {len(existing)} existing file(s); pass --force to replace them:")
        for path in existing:
            error(f"  {path.relative_to(project.repo_root)}")
        raise typer.Exit(code=1)

    env = _environment()
    for path, template_name in targets.items():
        rendered = env.get_template(template_name).render(**context)
        info(f"{'would write' if dry_run else 'writing'} {path.relative_to(project.repo_root)}")
        if dry_run:
            continue
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(rendered, encoding="utf-8")

    if not dry_run:
        _ensure_package_init(project.backend_dir / "tests" / "unit" / "tools" / "__init__.py")

    if dry_run:
        info("")
        info("dry-run complete — no files were written.")
        return

    info("")
    info(f"Tool '{slug}' generated. Two manual steps remain:")
    info(f"  1. Create the migration:  cd backend && uv run alembic revision --autogenerate -m 'add {slug} tables'")
    info("     Then read the generated migration before applying it.")
    info(f"  2. Grant the permission:  add '{permission}' to the relevant roles in")
    info("     backend/src/modules/platform/constants.py, then re-run scripts/create_platform_roles.py.")


def _ensure_package_init(path: Path) -> None:
    """Create an empty ``__init__.py`` so the generated tests are importable."""
    if path.exists():
        return
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text("", encoding="utf-8")
