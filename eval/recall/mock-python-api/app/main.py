"""mock-python-api 应用入口。"""

from fastapi import FastAPI

from app.routers.users import UserRouter


def create_app() -> FastAPI:
    """创建 FastAPI 应用实例。"""
    app = FastAPI(title="mock-api")
    app.include_router(UserRouter().router)
    return app
