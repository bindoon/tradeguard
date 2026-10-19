from sqlalchemy.dialects.mysql import insert


def upsert(model, rows: list[dict], fields: list[str]):
    statement = insert(model).values(rows)
    return statement.on_duplicate_key_update(**{k: getattr(statement.inserted, k) for k in fields})
