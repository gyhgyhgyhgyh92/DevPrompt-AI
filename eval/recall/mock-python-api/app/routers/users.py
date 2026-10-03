"""用户路由。"""

from fastapi import APIRouter, Depends

from app.models import User
from app.deps import get_db


class UserRouter:
    """用户相关接口集合。"""

    def __init__(self) -> None:
        self.router = APIRouter(prefix="/users")
        self.router.add_api_route("/", self.list_users, methods=["GET"])
        self.router.add_api_route("/", self.create_user, methods=["POST"])

    def list_users(self, db: object = Depends(get_db)) -> list[User]:
        """查询用户列表。"""
        return []

    def create_user(self, user: User, db: object = Depends(get_db)) -> User:
        """创建用户。"""
        return user
