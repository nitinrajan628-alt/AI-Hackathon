"""Execute compiled queries against the read-only review database."""
from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field

import pandas as pd

from models.evidence import CompiledQuery
from services.db import get_review_connection


class QueryExecutionError(Exception):
    pass


@dataclass
class RawQueryResult:
    df: pd.DataFrame
    row_count: int = 0
    metadata: dict = field(default_factory=dict)


def execute_query(compiled: CompiledQuery,
                  con: sqlite3.Connection | None = None) -> RawQueryResult:
    close = con is None
    if con is None:
        con = get_review_connection()
    try:
        cursor = con.execute(compiled.sql, compiled.parameters)
        columns = [d[0] for d in cursor.description]
        rows = cursor.fetchall()
        df = pd.DataFrame([tuple(r) for r in rows], columns=columns)
        return RawQueryResult(df=df, row_count=len(df),
                              metadata={"sql": compiled.sql,
                                        "parameters": compiled.parameters})
    except sqlite3.Error as exc:
        raise QueryExecutionError(str(exc)) from exc
    finally:
        if close:
            con.close()
