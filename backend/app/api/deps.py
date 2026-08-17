from typing import Annotated

from fastapi import Depends
from sqlalchemy.orm import Session

from app.database.session import get_db

DbSession = Annotated[Session, Depends(get_db)]
