import jwt
import structlog
import csv
import io
from fastapi import APIRouter, Depends, HTTPException, Query, Path, status, Security, Request
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from fastapi.responses import StreamingResponse
from typing import Optional, List, Any
from bson import ObjectId
from datetime import datetime, timezone, date, time
from core.config import settings
from core.db import db
from schemas.registration  import SubmissionOut


log = structlog.get_logger()
bearer = HTTPBearer(auto_error=False)
router = APIRouter(prefix="/api/admin")

# Admin auth
async def admin_required(
    credentials: HTTPAuthorizationCredentials = Security(bearer)
):
    if not credentials or not credentials.credentials:
        raise HTTPException(401, "Credenciais ausentes")
    try:
        payload = jwt.decode(
            credentials.credentials,
            settings.JWT_SECRET,
            algorithms=[settings.JWT_ALGORITHM],
        )
    except jwt.PyJWTError:
        raise HTTPException(401, "Token inválido")
    return payload

@router.get("/submissions", dependencies=[Depends(admin_required)], response_model=Any)
async def list_submissions(
    name: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    min_rating: Optional[int] = Query(None, ge=0, le=10),
    max_rating: Optional[int] = Query(None, ge=0, le=10),
    chosen: bool | None = Query(
        None, description="true=apenas escolhidos, false=apenas não escolhidos"
    ),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
    page: int = Query(1, ge=1),
    page_size: int = Query(20, ge=1, le=100),
) -> Any:
    filters: dict = {}

    if name:
        filters["name"] = {"$regex": name, "$options": "i"}
    if email:
        filters["email"] = {"$regex": email, "$options": "i"}

    if min_rating is not None or max_rating is not None:
        filters["rating"] = {}
        if min_rating is not None:
            filters["rating"]["$gte"] = min_rating
        if max_rating is not None:
            filters["rating"]["$lte"] = max_rating

    if chosen is True:
        filters["flaggedChosen"] = True
    elif chosen is False:
        filters["flaggedChosen"] = {"$ne": True}

    if date_from or date_to:
        dt_filter: dict = {}
        if date_from:
            start = datetime.combine(date_from, time.min).replace(tzinfo=timezone.utc)
            dt_filter["$gte"] = start
        if date_to:
            end = datetime.combine(date_to, time.max).replace(tzinfo=timezone.utc)
            dt_filter["$lte"] = end
        filters["createdAt"] = dt_filter

    skip = (page - 1) * page_size

    cursor = (
        db.registrations
        .find(filters)
        .sort("createdAt", -1)
        .skip(skip)
        .limit(page_size)
    )

    results = []
    async for doc in cursor:
        results.append({
            "id": str(doc["_id"]),
            "name": doc["name"],
            "email": doc["email"],
            "phone": doc["phone"],
            "videoUrl": doc.get("videoUrl"),
            "thumbnailUrl": doc.get("thumbnailUrl"),
            "status": doc["status"],
            "createdAt": doc["createdAt"],
            "rating": doc.get("rating"),
            "comments": doc.get("comments"),
            "flaggedChosen": doc.get("flaggedChosen"),
        })

    total = await db.registrations.count_documents(filters)

    return {
        "data": results,
        "page": page,
        "page_size": page_size,
        "total": total
    }

@router.get("/submissions/export", response_class=StreamingResponse)
async def export_submissions(
    name: Optional[str] = Query(None),
    email: Optional[str] = Query(None),
    min_rating: Optional[int] = Query(None, ge=0, le=10),
    max_rating: Optional[int] = Query(None, ge=0, le=10),
    winner: Optional[bool] = Query(None, description="Filtrar escolhidos"),
    date_from: Optional[date] = Query(None),
    date_to: Optional[date] = Query(None),
):
    filters: dict = {}
    if name:
        filters["name"] = {"$regex": name, "$options": "i"}
    if email:
        filters["email"] = {"$regex": email, "$options": "i"}
    if min_rating is not None or max_rating is not None:
        filters["rating"] = {}
        if min_rating is not None:
            filters["rating"]["$gte"] = min_rating
        if max_rating is not None:
            filters["rating"]["$lte"] = max_rating
    if winner is not None:
        filters["flaggedChosen"] = winner
    if date_from or date_to:
        dtf: dict = {}
        if date_from:
            dtf["$gte"] = datetime.combine(date_from, time.min).replace(tzinfo=timezone.utc)
        if date_to:
            dtf["$lte"] = datetime.combine(date_to, time.max).replace(tzinfo=timezone.utc)
        filters["createdAt"] = dtf

    cursor = db.registrations.find(filters).sort("createdAt", -1)

    async def csv_generator():
        buf = io.StringIO()
        writer = csv.writer(buf)
        # cabeçalho
        writer.writerow([
            "id", "name", "email", "phone", "createdAt", "status",
            "rating", "comments", "flaggedChosen", "videoUrl", "thumbnailUrl"
        ])
        yield buf.getvalue()
        buf.seek(0); buf.truncate(0)

        async for doc in cursor:
            writer.writerow([
                str(doc["_id"]),
                doc.get("name", ""),
                doc.get("email", ""),
                doc.get("phone", ""),
                doc.get("createdAt").isoformat(),
                doc.get("status", ""),
                doc.get("rating", ""),
                doc.get("comments", ""),
                str(doc.get("flaggedChosen", False)),
                doc.get("videoUrl", ""),
                doc.get("thumbnailUrl", "")
            ])
            yield buf.getvalue()
            buf.seek(0); buf.truncate(0)

    headers = {
        "Content-Disposition": 'attachment; filename="submissions.csv"',
        "Content-Type": "text/csv; charset=utf-8"
    }
    log.info("submissions-exported", filters=filters)
    return StreamingResponse(csv_generator(), headers=headers)

@router.get("/submissions/{submission_id}", dependencies=[Depends(admin_required)])
async def get_submission(
    submission_id: str = Path(..., title="ID da submissão")
):
    """ Get all submission details."""
    try:
        oid = ObjectId(submission_id)
    except Exception:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="ID inválido")
    doc = await db.registrations.find_one({'_id': oid})
    if not doc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Submissão não encontrada")
    doc['id'] = str(doc['_id'])
    return doc

@router.patch("/submissions/{submission_id}/rating")
async def update_rating(
    request: Request,
    submission_id: str = Path(..., title="Id da submissão"),
    rating: int = Query(..., ge=0, le=10),
    comments: Optional[str] = Query(None),
    flagged_chosen: bool = Query(..., description="Marcar como escolhido")
):
    update_fields = {
        "rating": rating,
        "reviewedAt": datetime.now(timezone.utc),
    }

    if flagged_chosen:
        update_fields["flaggedChosen"] = True
        update_fields["status"] = "chosen"
    else:
        update_fields["flaggedChosen"] = False
        update_fields["status"] = "reviewed"

    if comments is not None:
        update_fields["comments"] = comments

    result = await db.registrations.update_one(
        {"_id": submission_id},
        {"$set": update_fields}
    )
    if result.modified_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submissão não encontrada ou sem alterações"
        )

    doc = await db.registrations.find_one({"_id": submission_id})
    if not doc:
        raise HTTPException(500, "Documento desapareceu após atualização")

    log.info("submission-updated", id=submission_id, updates=update_fields)
    return {
        "id": submission_id,
        "rating": doc.get("rating"),
        "comments": doc.get("comments", ""),
        "flaggedChosen": doc.get("flaggedChosen", False),
        "status": doc.get("status")
    }

@router.delete("/submissions/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_submission(
    submission_id: str = Path(..., description="ID da submissão a ser excluída")
):
    result = await db.registrations.delete_one({"_id": submission_id})
    if result.deleted_count == 0:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Submissão não encontrada"
        )
    log.info("submission-deleted", id=submission_id)
    return  # 204 No Content