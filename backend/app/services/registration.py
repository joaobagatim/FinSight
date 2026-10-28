"""Create identities atomically without disclosing whether an email exists."""

from sqlalchemy.exc import IntegrityError, SQLAlchemyError
from sqlalchemy.orm import Session

from app.core.security import hash_password
from app.models.user import User
from app.schemas.auth import RegistrationInput


class RegistrationUnavailable(Exception):
    """Publicly safe signal; never include driver errors or credentials."""


def register_user(session: Session, data: RegistrationInput) -> None:
    encoded = hash_password(data.password.get_secret_value())
    try:
        session.add(User(name=data.name, email=data.email, password_hash=encoded))
        session.commit()
    except IntegrityError as error:
        session.rollback()
        if not (
            getattr(error.orig, "sqlstate", None) == "23505"
            and getattr(getattr(error.orig, "diag", None), "constraint_name", None)
            == "uq_users_email"
        ):
            raise RegistrationUnavailable() from None
    except SQLAlchemyError:
        session.rollback()
        raise RegistrationUnavailable() from None
