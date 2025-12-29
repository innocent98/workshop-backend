"""
File upload utilities for profile pictures.
Implements security best practices for file handling.
"""
import os
import uuid
from typing import Optional
from fastapi import UploadFile, HTTPException, status
from PIL import Image
import io

from app.core.logger import log


# Allowed image extensions
ALLOWED_EXTENSIONS = {'.jpg', '.jpeg', '.png', '.gif'}
MAX_FILE_SIZE = 5 * 1024 * 1024  # 5MB
MAX_IMAGE_DIMENSION = 1080  # Max 1080x1080 as per documentation


def validate_image_file(file: UploadFile) -> None:
    """
    Validate uploaded image file.

    Args:
        file: Uploaded file

    Raises:
        HTTPException: If file is invalid
    """
    # Check file extension
    file_ext = os.path.splitext(file.filename)[1].lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid file type. Allowed types: {', '.join(ALLOWED_EXTENSIONS)}"
        )

    # Check content type
    if not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image"
        )


async def save_profile_picture(file: UploadFile, user_id: str) -> Optional[str]:
    """
    Save and process profile picture.

    Args:
        file: Uploaded image file
        user_id: User ID for unique naming

    Returns:
        URL/path to saved image, or None if failed

    Security measures:
    - File type validation
    - Size validation
    - Image dimension limits
    - Unique filename generation
    - Content verification (actual image check)
    """
    try:
        # Validate file
        validate_image_file(file)

        # Read file content
        content = await file.read()

        # Check file size
        if len(content) > MAX_FILE_SIZE:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size exceeds maximum allowed size ({MAX_FILE_SIZE / 1024 / 1024}MB)"
            )

        # Verify it's actually an image and resize if needed
        try:
            image = Image.open(io.BytesIO(content))

            # Resize if larger than max dimensions
            if image.width > MAX_IMAGE_DIMENSION or image.height > MAX_IMAGE_DIMENSION:
                image.thumbnail((MAX_IMAGE_DIMENSION, MAX_IMAGE_DIMENSION), Image.Resampling.LANCZOS)

            # Generate unique filename
            file_ext = os.path.splitext(file.filename)[1].lower()
            unique_filename = f"{user_id}_{uuid.uuid4().hex}{file_ext}"

            # TODO: Upload to cloud storage (S3, Cloudinary, etc.)
            # For now, save locally
            upload_dir = "uploads/profile_pictures"
            os.makedirs(upload_dir, exist_ok=True)

            file_path = os.path.join(upload_dir, unique_filename)

            # Save processed image
            image.save(file_path, quality=85, optimize=True)

            # Return URL (in production, return cloud storage URL)
            image_url = f"/static/profile_pictures/{unique_filename}"

            log.info(f"Profile picture saved for user {user_id}: {image_url}")
            return image_url

        except Exception as e:
            log.error(f"Failed to process image: {str(e)}")
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Invalid image file or corrupted image"
            )

    except HTTPException:
        raise
    except Exception as e:
        log.error(f"Failed to save profile picture: {str(e)}")
        return None


def delete_profile_picture(file_path: str) -> bool:
    """
    Delete profile picture file.

    Args:
        file_path: Path to file to delete

    Returns:
        True if deleted successfully
    """
    try:
        if os.path.exists(file_path):
            os.remove(file_path)
            log.info(f"Deleted profile picture: {file_path}")
            return True
        return False
    except Exception as e:
        log.error(f"Failed to delete profile picture {file_path}: {str(e)}")
        return False
