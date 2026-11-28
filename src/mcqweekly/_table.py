"""Interface to mcqreport.table (#62): the weekly table builder and its markdown renderer.

build_table(reports, window, closed_at=None, incomplete_reasons=None) -> dict and render_md(table) -> str.
`run_weekly` takes the module's two functions as a namespace, so tests can inject a fake without touching this file.
"""

from types import SimpleNamespace

from mcqreport import table as mcq_table


def load_table_api():
    return SimpleNamespace(build_table=mcq_table.build_table, render_md=mcq_table.render_md)
