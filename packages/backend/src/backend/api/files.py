from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.execution import TaskArtifact
from backend.storage.minio_client import MinioStorage

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/presign")
async def presign_url(key: str = Query(..., description="MinIO object key")):
    try:
        storage = MinioStorage()
        url = storage.presign_url(key)
        return {"url": url}
    except Exception as e:
        raise HTTPException(500, f"Failed to generate presign URL: {e}")


@router.get("/{artifact_id}/download")
async def download_artifact(
    artifact_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TaskArtifact).where(TaskArtifact.id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(404, "Artifact not found")

    storage = MinioStorage()
    url = storage.presign_url(artifact.minio_key)
    from fastapi.responses import RedirectResponse
    return RedirectResponse(url)
