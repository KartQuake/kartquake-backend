from app.db.base_class import Base

# Import all models so that Base.metadata has them
# (order: define Base first, then import models)

from app.models.user import User  # noqa: F401
from app.models.item_intent import ItemIntent  # noqa: F401
from app.models.store import  Store, StoreLocation, UserStoreMembership, Coupon

from app.models.chat import ChatSession, ChatMessage  # noqa: F401
from app.models.watchlist import WatchlistItem  # noqa: F401

from app.models.watchlist import WatchlistItem

