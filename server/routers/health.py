from fastapi import APIRouter

router = APIRouter(tags=["meta"])


@router.get("/api/v1/health")
def health_check():
    return {
        "status": "healthy",
        "service": "Thai GovDoc AI Studio API",
        "version": "2.0.0",
        "standards": "ระเบียบสำนักนายกรัฐมนตรีว่าด้วยงานสารบรรณ พ.ศ. ๒๕๒๖",
    }
