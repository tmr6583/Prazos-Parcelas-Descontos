from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.orm import Session
from passlib.context import CryptContext

from app.config import Settings
from app.models import User


# Usa PBKDF2 como padrão novo e mantém suporte de verificação para hashes bcrypt legados.
pwd_context = CryptContext(schemes=["pbkdf2_sha256", "bcrypt"], deprecated="auto")


class AuthService:
    def __init__(self, db: Session) -> None:
        self.db = db

    @staticmethod
    def hash_password(password: str) -> str:
        return pwd_context.hash(password)

    @staticmethod
    def verify_password(password: str, password_hash: str) -> bool:
        return pwd_context.verify(password, password_hash)

    def bootstrap_master_user(self, settings: Settings) -> User:
        existing = self.db.scalar(select(User).where(User.email == str(settings.master_user_email)))
        if existing:
            if existing.is_deleted:
                existing.is_deleted = False
                existing.is_active = True
            existing.is_master = True
            if not existing.password_hash:
                existing.password_hash = self.hash_password(settings.master_user_password)
            self.db.commit()
            self.db.refresh(existing)
            return existing

        user = User(
            email=str(settings.master_user_email),
            password_hash=self.hash_password(settings.master_user_password),
            is_master=True,
            is_active=True,
            is_deleted=False,
        )
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def authenticate(self, email: str, password: str) -> User | None:
        user = self.db.scalar(
            select(User).where(
                User.email == email.strip().lower(),
                User.is_active.is_(True),
                User.is_deleted.is_(False),
            ),
        )
        if user is None or not self.verify_password(password, user.password_hash):
            return None
        return user

    def list_users(self) -> list[User]:
        statement = (
            select(User)
            .where(User.is_deleted.is_(False))
            .order_by(User.is_master.desc(), User.email.asc())
        )
        return list(self.db.scalars(statement))

    def create_user(self, email: str, password: str) -> User:
        normalized_email = email.strip().lower()
        existing = self.db.scalar(select(User).where(User.email == normalized_email))
        if existing and not existing.is_deleted:
            raise ValueError("Já existe um usuário com este e-mail.")

        password_hash = self.hash_password(password)
        if existing and existing.is_deleted:
            existing.password_hash = password_hash
            existing.is_active = True
            existing.is_deleted = False
            self.db.commit()
            self.db.refresh(existing)
            return existing

        user = User(email=normalized_email, password_hash=password_hash)
        self.db.add(user)
        self.db.commit()
        self.db.refresh(user)
        return user

    def soft_delete_user(self, user_id: int) -> None:
        user = self.db.get(User, user_id)
        if user is None or user.is_deleted:
            raise ValueError("Usuário não encontrado.")
        if user.is_master:
            raise ValueError("O usuário mestre não pode ser excluído.")

        user.is_active = False
        user.is_deleted = True
        self.db.commit()

    def reset_password(self, user_id: int, password: str) -> None:
        user = self.db.get(User, user_id)
        if user is None or user.is_deleted:
            raise ValueError("Usuário não encontrado.")
        user.password_hash = self.hash_password(password)
        self.db.commit()

    def get_by_id(self, user_id: int) -> User | None:
        user = self.db.get(User, user_id)
        if user is None or user.is_deleted or not user.is_active:
            return None
        return user
