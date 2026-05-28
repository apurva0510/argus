from ai_infra_watcher.core.db import session_scope
from ai_infra_watcher.core.models import Company


def get_company_options() -> list[str]:
    with session_scope() as session:
        symbols = session.query(Company.symbol).filter(Company.is_active.is_(True)).order_by(Company.symbol).all()
    return [row[0] for row in symbols]
