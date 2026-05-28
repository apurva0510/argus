from argus.core.db import session_scope
from argus.core.models import Company


def get_company_options() -> list[str]:
    with session_scope() as session:
        symbols = session.query(Company.symbol).filter(Company.is_active.is_(True)).order_by(Company.symbol).all()
    return [row[0] for row in symbols]
