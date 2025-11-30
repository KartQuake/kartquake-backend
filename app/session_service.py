# backend/session_service.py
import uuid
from datetime import datetime

from sqlmodel import Session, select

from .models import TripSession, PlanConstraints


def get_or_create_session(db: Session, session_id: str | None) -> TripSession:
    """
    If session_id is given and exists, return it.
    Otherwise create a new TripSession (with that id if valid, else a new UUID).
    """
    if session_id:
        try:
            sid = uuid.UUID(session_id)
        except ValueError:
            sid = uuid.uuid4()
        stmt = select(TripSession).where(TripSession.id == sid)
        existing = db.exec(stmt).first()
        if existing:
            return existing
        sess = TripSession(id=sid)
    else:
        sess = TripSession()

    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess


def get_constraints(sess: TripSession) -> PlanConstraints:
    """
    Convert DB dict to PlanConstraints, or return default if empty.
    """
    if sess.constraints:
        return PlanConstraints(**sess.constraints)
    return PlanConstraints()


def save_constraints(db: Session, sess: TripSession, constraints: PlanConstraints) -> TripSession:
    """
    Save constraints back to DB and update timestamp.
    """
    sess.constraints = constraints.model_dump()
    sess.updated_at = datetime.utcnow()
    db.add(sess)
    db.commit()
    db.refresh(sess)
    return sess
