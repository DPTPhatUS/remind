"""Transactional removal of recordings and dependent unfinished work."""

import aiosqlite


async def cancel_clip(db: aiosqlite.Connection, clip_id: str, path: str | None) -> None:
    """The caller selects the clip and owns the transaction."""
    if path:
        await db.execute("INSERT OR IGNORE INTO cleanup VALUES(?)", (path,))
    await db.execute("UPDATE clips SET cancelled=1,path=NULL,timeline='[]' WHERE id=?", (clip_id,))
    await db.execute(
        "UPDATE jobs SET status='cancelled',lease_token=NULL,payload='{}' "
        "WHERE clip_id=? AND status!='done'",
        (clip_id,),
    )
