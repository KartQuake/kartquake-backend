from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db.session import get_db
from app.models.user import User, UserCreate, UserRead

router = APIRouter()

@router.post("/users", response_model=UserRead)
def create_user(user_in: UserCreate, db: Session = Depends(get_db)):
    # For anonymous users, email may be None
    user = User(
        email=user_in.email,
        name=user_in.name,
        zip_code=user_in.zip_code,
        auth_provider=user_in.auth_provider or "anonymous",
        auth_provider_subject=user_in.auth_provider_subject,
        # plan & free-tier use defaults from the model
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user
