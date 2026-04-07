import re

with open('core/pg_admin_store.py', 'r', encoding='utf-8') as f:
    content = f.read()

# 1. Modify is_resource_blocked
target1 = '''    def is_resource_blocked(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM blocked_resources
                    WHERE site_id = %s AND resource_id = %s
                    LIMIT 1
                    """,
                    (str(site_id), int(resource_id)),
                )
                return cur.fetchone() is not None'''
replacement1 = '''    def is_resource_blocked(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT 1
                    FROM blocked_resources
                    WHERE resource_id = %s
                    LIMIT 1
                    """,
                    (int(resource_id),),
                )
                return cur.fetchone() is not None'''

# 2. Modify get_blocked_resource_ids
target2 = '''    def get_blocked_resource_ids(self, *, site_id: str, resource_ids: list[int]) -> set[int]:
        ids = sorted({int(x) for x in (resource_ids or [])})
        if not ids:
            return set()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT resource_id
                    FROM blocked_resources
                    WHERE site_id = %s
                      AND resource_id = ANY(%s)
                    """,
                    (str(site_id), ids),
                )
                rows = cur.fetchall()
        return {int(row[0]) for row in rows if row and row[0] is not None}'''
replacement2 = '''    def get_blocked_resource_ids(self, *, site_id: str, resource_ids: list[int]) -> set[int]:
        ids = sorted({int(x) for x in (resource_ids or [])})
        if not ids:
            return set()
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    """
                    SELECT resource_id
                    FROM blocked_resources
                    WHERE resource_id = ANY(%s)
                    """,
                    (ids,),
                )
                rows = cur.fetchall()
        return {int(row[0]) for row in rows if row and row[0] is not None}'''

# 3. Modify unblock_resource
target3 = '''    def unblock_resource(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_resources WHERE site_id = %s AND resource_id = %s",
                    (str(site_id), int(resource_id)),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted'''
replacement3 = '''    def unblock_resource(self, *, site_id: str, resource_id: int) -> bool:
        with self._conn() as conn:
            with conn.cursor() as cur:
                cur.execute(
                    "DELETE FROM blocked_resources WHERE resource_id = %s",
                    (int(resource_id),),
                )
                deleted = cur.rowcount > 0
            conn.commit()
        return deleted'''

for (t, r) in [(target1, replacement1), (target2, replacement2), (target3, replacement3)]:
    tn = t.replace('\r\n', '\n')
    rn = r.replace('\r\n', '\n')
    content = content.replace('\r\n', '\n').replace(tn, rn)

with open('core/pg_admin_store.py', 'w', encoding='utf-8') as f:
    f.write(content)

print("Replaced successfully")
