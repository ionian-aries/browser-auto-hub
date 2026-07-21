from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from backend.database import get_session
from backend.models.execution import TaskArtifact
from backend.storage.minio_client import MinioStorage

router = APIRouter(prefix="/api/files", tags=["files"])


@router.get("/{artifact_id}/download")
async def download_file(
    artifact_id: str, session: AsyncSession = Depends(get_session)
):
    result = await session.execute(
        select(TaskArtifact).where(TaskArtifact.id == artifact_id)
    )
    artifact = result.scalar_one_or_none()
    if artifact is None:
        raise HTTPException(404, "File not found")

    storage = MinioStorage()
    data = storage.download(artifact.minio_key)
    return Response(
        content=data,
        media_type=artifact.content_type,
        headers={"Content-Disposition": f'attachment; filename="{artifact.file_name}"'},
    )
