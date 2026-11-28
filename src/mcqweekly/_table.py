"""Interface layer to mcqreport.table (#62). Not merged yet: until then the real table is missing and callers inject a fake.

Contract used here: build_table(reports, window, closed_at=None, incomplete_reasons=None) -> dict
and render_md(table) -> str. If #62 renames anything, change it here and nowhere else.
"""

from types import SimpleNamespace

from mcqreport.common import ToolError


def load_table_api():
    try:
        from mcqreport import table as mod
    except ImportError as e:
        raise ToolError("table_unavailable", "mcqreport.table is not available (#62 not merged)") from e
    return SimpleNamespace(build_table=mod.build_table, render_md=mod.render_md)
