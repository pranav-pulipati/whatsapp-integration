from fastapi import APIRouter

from app.api import accounts, analytics, auth, browse, ops

router = APIRouter()
router.include_router(auth.router)
router.include_router(accounts.router)
router.include_router(browse.router)
router.include_router(analytics.router)
router.include_router(ops.router)
