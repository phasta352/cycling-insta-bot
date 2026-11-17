"""Uploads graphics to Cloudinary so Instagram can fetch them from a public link."""
from pathlib import Path

import cloudinary
import cloudinary.api
import cloudinary.uploader


def configure(secrets) -> None:
    cloudinary.config(
        cloud_name=secrets.cloudinary_name,
        api_key=secrets.cloudinary_key,
        api_secret=secrets.cloudinary_secret,
        secure=True,
    )


def upload(path: Path, public_id: str) -> str:
    res = cloudinary.uploader.upload(
        str(path), folder="cycling-bot", public_id=public_id, overwrite=True, resource_type="image"
    )
    return res["secure_url"]


def ping() -> str:
    cloudinary.api.ping()
    return "ok"
