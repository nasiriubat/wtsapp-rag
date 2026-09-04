import json

from fastapi.responses import StreamingResponse

import db


def stream(sql, params, filename, batch=500):
    """Stream rows as JSON lines through a server-side cursor, so a large
    table is never held in memory and the response starts immediately."""

    def lines():
        # Named cursors need a transaction even on an autocommit connection.
        with db.connect() as conn, conn.transaction(), conn.cursor(name="jsonl") as cur:
            cur.itersize = batch
            cur.execute(sql, params)
            buf = []
            for row in cur:
                buf.append(json.dumps(row, default=str))
                if len(buf) >= batch:
                    yield "\n".join(buf) + "\n"
                    buf = []
            if buf:
                yield "\n".join(buf) + "\n"

    # ASCII-only name: response headers are latin-1 and group names are not.
    headers = {"content-disposition": f'attachment; filename="{filename}"'}
    return StreamingResponse(lines(), media_type="application/x-ndjson", headers=headers)
