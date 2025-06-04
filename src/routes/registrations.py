import os
import tempfile
import subprocess

from fastapi import APIRouter, HTTPException, Depends, Request
from schemas.registration import (
    RegistrationInitRequest,
    RegistrationInitResponse,
    RegistrationCompleteRequest,
    RegistrationCompleteResponse
)
from core.db import db
from core.redis import redis
from utils.s3 import (
    create_presigned_upload,
    create_presigned_download,
    public_url,
    s3_client
)
from core.config import settings
from datetime import datetime, timezone, timedelta
import structlog, uuid

log = structlog.get_logger()
router = APIRouter(prefix="/api/registrations")


async def rate_limiter(request: Request):
    ip = request.client.host
    today = datetime.now(timezone.utc).date()
    key = f"rl:{ip}:{today}"
    count = await redis.get(key) or 0
    if int(count) >= settings.RATE_LIMIT_PER_DAY:
        raise HTTPException(429, "Quota diária excedida")
    await redis.incr(key)
    # expira à meia-noite UTC
    tomorrow = today + timedelta(days=1)
    secs = int((datetime.combine(tomorrow, datetime.min.time())
                .replace(tzinfo=timezone.utc)
                - datetime.now(timezone.utc)).total_seconds())
    await redis.expire(key, secs)


@router.post("/init", response_model=RegistrationInitResponse)
async def init_registration(
    data: RegistrationInitRequest,
    _: None = Depends(rate_limiter)
):
    reg_id = str(uuid.uuid4())
    video = create_presigned_upload("videos", data.videoContentType)
    thumb = create_presigned_upload("thumbnails", "image/jpeg")

    doc = {
        "_id": reg_id,
        "name": data.name,
        "email": data.email,
        "phone": data.phone,
        "videoKey": video["key"],
        "thumbnailKey": thumb["key"],
        "status": "initiated",
        "createdAt": datetime.now(timezone.utc),
    }
    await db.registrations.insert_one(doc)
    log.info("registration_initiated", id=reg_id)

    return RegistrationInitResponse(
        id=reg_id,
        videoUploadUrl=video["url"],
        thumbnailUploadUrl=thumb["url"]
    )


@router.post("/complete", response_model=RegistrationCompleteResponse)
async def complete_registration(
    data: RegistrationCompleteRequest
):
    reg = await db.registrations.find_one({"_id": data.id})
    if not reg:
        raise HTTPException(404, "Registro não encontrado")
    if reg.get("status") != "initiated":
        raise HTTPException(400, "Registro já processado ou inválido")

    video_key = reg["videoKey"]
    with tempfile.NamedTemporaryFile(suffix=".mp4", delete=False) as tmp_vid:
        s3_client.download_fileobj(
            settings.S3_BUCKET, video_key, tmp_vid
        )
        tmp_vid_path = tmp_vid.name

    thumb_key = reg["thumbnailKey"]
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp_img:
        tmp_img_path = tmp_img.name

    cmd = [
        "ffmpeg",
        "-y",
        "-i", tmp_vid_path,
        "-ss", "00:00:01.000",
        "-vframes", "1",
        "-q:v", "2",
        tmp_img_path
    ]
    subprocess.run(cmd, check=True)

    with open(tmp_img_path, "rb") as image_data:
        s3_client.put_object(
            Bucket=settings.S3_BUCKET,
            Key=thumb_key,
            Body=image_data,
            ContentType="image/jpeg"
        )

    os.remove(tmp_vid_path)
    os.remove(tmp_img_path)

    # video_url = create_presigned_download(reg["videoKey"])
    # thumb_url = create_presigned_download(reg["thumbnailKey"])

    video_url = public_url(reg["videoKey"])
    thumb_url = public_url(reg["thumbnailKey"])

    await db.registrations.update_one(
        {"_id": data.id},
        {"$set": {
            "status":       "pending",
            "videoUrl":     video_url,
            "thumbnailUrl": thumb_url
        }}
    )
    log.info("registration_completed", id=data.id)

    await redis.rpush("registration_queue", data.id)

    return RegistrationCompleteResponse(
        id = reg["_id"],
        name = reg["name"],
        email = reg["email"],
        phone = reg["phone"],
        videoUrl = video_url,
        thumbnailUrl = thumb_url,
        status = "pending",
        createdAt = reg["createdAt"]
    )
