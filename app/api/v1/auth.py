# app/api/v1/auth.py

import os
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session

from authlib.integrations.starlette_client import OAuth, OAuthError

from app.db.session import get_db
from app.models.user import User

router = APIRouter(prefix="/auth", tags=["auth"])

# -------------------------------------------------------------------
# OAuth client configuration (Authlib)
# -------------------------------------------------------------------

oauth = OAuth()

# Google OAuth registration
oauth.register(
    name="google",
    client_id=os.getenv("GOOGLE_CLIENT_ID"),
    client_secret=os.getenv("GOOGLE_CLIENT_SECRET"),
    server_metadata_url="https://accounts.google.com/.well-known/openid-configuration",
    client_kwargs={"scope": "openid email profile"},
)


# NOTE: Real Sign in with Apple is more complex and requires an Apple
# developer account, a private key, and client secret JWTs.
# Here we register a stub "apple" provider so the endpoints exist,
# but we do *not* implement full OAuth yet. See endpoints below.
APPLE_ENABLED = bool(os.getenv("APPLE_CLIENT_ID"))


def get_frontend_base_url() -> str:
    """
    Where we redirect after successful auth.
    Example: https://kartquake.vercel.app
    """
    return os.getenv("FRONTEND_BASE_URL", "http://localhost:5173")


# -------------------------------------------------------------------
# Google OAuth
# -------------------------------------------------------------------

@router.get("/google/start")
async def google_start(request: Request):
    """
    Step 1: Redirect the user to Google for sign-in.
    """
    if not os.getenv("GOOGLE_CLIENT_ID") or not os.getenv("GOOGLE_CLIENT_SECRET"):
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Google OAuth is not configured on the server",
        )

    # This is the callback URL Google will redirect back to
    redirect_uri = request.url_for("google_callback")
    return await oauth.google.authorize_redirect(request, redirect_uri)


@router.get("/google/callback", name="google_callback")
async def google_callback(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Step 2: Google redirects here after user signs in.
    We:
      - Exchange code for tokens
      - Fetch userinfo
      - Create or fetch a User in our DB
      - Redirect to frontend with ?user_id=<uuid>
    """
    try:
        token = await oauth.google.authorize_access_token(request)
    except OAuthError as e:
        # Something went wrong in the OAuth handshake
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Google auth error: {e.error}",
        )

    # Try userinfo from token (OpenID Connect userinfo)
    userinfo = token.get("userinfo")
    if not userinfo:
        # Fallback to parsing ID token if userinfo is not present
        userinfo = await oauth.google.parse_id_token(request, token)

    if not userinfo:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google auth error: no user info returned",
        )

    email: Optional[str] = userinfo.get("email")
    sub: Optional[str] = userinfo.get("sub")
    name: Optional[str] = (
        userinfo.get("name")
        or f"{userinfo.get('given_name', '')} {userinfo.get('family_name', '')}".strip()
    )

    if not sub:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Google auth error: missing subject (sub) claim",
        )

    # 1) Try to find by provider+subject
    user = (
        db.query(User)
        .filter(
            User.auth_provider == "google",
            User.auth_provider_subject == sub,
        )
        .first()
    )

    # 2) If not found but email exists, try by email
    if not user and email:
        user = db.query(User).filter(User.email == email).first()

    # 3) Create new user if none exists
    if not user:
        user = User(
            email=email,
            name=name,
            auth_provider="google",
            auth_provider_subject=sub,
            # plan, free limits, etc. use defaults
        )
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        # Optionally update name/email if they changed
        updated = False
        if email and user.email != email:
            user.email = email
            updated = True
        if name and user.name != name:
            user.name = name
            updated = True
        if updated:
            db.add(user)
            db.commit()
            db.refresh(user)

    frontend_base = get_frontend_base_url()
    # Append ?user_id=<uuid> or &user_id= if query already exists
    sep = "&" if "?" in frontend_base else "?"
    redirect_url = f"{frontend_base}{sep}user_id={user.id}"
    return RedirectResponse(redirect_url)


# -------------------------------------------------------------------
# Apple "stub" auth – creates Apple-tagged users without real Apple login
# -------------------------------------------------------------------
# This is *not* real Sign in with Apple.
# Real Apple login requires:
#  - Apple developer account
#  - private key + key id + team id
#  - JWT client secret for Apple
#
# For now, we implement a placeholder flow so your UI buttons work:
# - /auth/apple/start just creates a new user with auth_provider="apple"
#   and redirects back.
# You can replace this later with a real Apple OAuth implementation.


@router.get("/apple/start")
async def apple_start(
    request: Request,
    db: Session = Depends(get_db),
):
    """
    Placeholder Apple auth that:
      - Creates a new user with auth_provider='apple'
      - Redirects back to frontend with ?user_id=<uuid>

    This is NOT a real Sign in with Apple implementation.
    Replace it later when you set up a proper Apple OAuth flow.
    """
    # In a real Apple implementation, you would redirect to Apple here.
    # For now, we just create a user record.

    # You could optionally require some query params here (like email hint),
    # but we'll keep it simple.
    user = User(
        email=None,
        name="Apple User",
        auth_provider="apple",
        auth_provider_subject=None,
    )
    db.add(user)
    db.commit()
    db.refresh(user)

    frontend_base = get_frontend_base_url()
    sep = "&" if "?" in frontend_base else "?"
    redirect_url = f"{frontend_base}{sep}user_id={user.id}"
    return RedirectResponse(redirect_url)
