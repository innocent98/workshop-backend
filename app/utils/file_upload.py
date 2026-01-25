"""
File upload utilities for images (profile pictures, portfolio, etc.).
Supports both local storage and Cloudinary.
Implements security best practices for file handling.
"""
import os
import uuid
import io
from typing import Optional, Tuple
from fastapi import UploadFile, HTTPException, status
from PIL import Image
import cloudinary
import cloudinary.uploader
import cloudinary.api

from app.core.logger import logger
from app.core.config import settings


# Initialize Cloudinary if credentials are provided
if settings.CLOUDINARY_CLOUD_NAME and settings.CLOUDINARY_API_KEY and settings.CLOUDINARY_API_SECRET:
    cloudinary.config(
        cloud_name=settings.CLOUDINARY_CLOUD_NAME,
        api_key=settings.CLOUDINARY_API_KEY,
        api_secret=settings.CLOUDINARY_API_SECRET,
        secure=True
    )
    logger.info("Cloudinary initialized successfully")
else:
    logger.warning("Cloudinary credentials not configured - using local storage")


# File validation constants
MAX_FILE_SIZE = settings.MAX_UPLOAD_SIZE_MB * 1024 * 1024  # Convert MB to bytes
ALLOWED_EXTENSIONS = set(f".{ext}" for ext in settings.ALLOWED_IMAGE_EXTENSIONS)
MAX_IMAGE_DIMENSION = 1080  # Max 1080x1080


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
    if not file.content_type or not file.content_type.startswith('image/'):
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="File must be an image"
        )


def process_image(content: bytes, max_dimension: int = MAX_IMAGE_DIMENSION) -> Tuple[Image.Image, str]:
    """
    Process and optimize image.

    Args:
        content: Image file content bytes
        max_dimension: Maximum width/height

    Returns:
        Tuple of (processed PIL Image, format)

    Raises:
        HTTPException: If image is invalid
    """
    try:
        image = Image.open(io.BytesIO(content))

        # Convert RGBA to RGB for JPEG compatibility
        if image.mode in ('RGBA', 'LA', 'P'):
            background = Image.new('RGB', image.size, (255, 255, 255))
            if image.mode == 'P':
                image = image.convert('RGBA')
            background.paste(image, mask=image.split()[-1] if image.mode in ('RGBA', 'LA') else None)
            image = background

        # Resize if larger than max dimensions
        if image.width > max_dimension or image.height > max_dimension:
            image.thumbnail((max_dimension, max_dimension), Image.Resampling.LANCZOS)
            logger.info(f"Resized image from {image.width}x{image.height} to fit {max_dimension}x{max_dimension}")

        # Determine format
        img_format = image.format or 'JPEG'
        if img_format not in ['JPEG', 'PNG', 'GIF', 'WEBP']:
            img_format = 'JPEG'

        return image, img_format

    except Exception as e:
        logger.error(f"Failed to process image: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid image file or corrupted image"
        )


async def upload_to_cloudinary(
    image: Image.Image,
    img_format: str,
    folder: str,
    public_id: Optional[str] = None
) -> str:
    """
    Upload image to Cloudinary.

    Args:
        image: PIL Image object
        img_format: Image format (JPEG, PNG, etc.)
        folder: Cloudinary folder path
        public_id: Optional custom public ID

    Returns:
        Cloudinary secure URL

    Raises:
        HTTPException: If upload fails
    """
    try:
        # Convert image to bytes
        img_byte_arr = io.BytesIO()
        image.save(img_byte_arr, format=img_format, quality=85, optimize=True)
        img_byte_arr.seek(0)

        # Upload to Cloudinary
        upload_options = {
            "folder": folder,
            "resource_type": "image",
            "format": img_format.lower(),
            "overwrite": False,
            "quality": "auto:good",
        }

        if public_id:
            upload_options["public_id"] = public_id

        result = cloudinary.uploader.upload(img_byte_arr, **upload_options)

        logger.info(f"Image uploaded to Cloudinary: {result['secure_url']}")
        return result['secure_url']

    except Exception as e:
        logger.error(f"Cloudinary upload failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to upload image to cloud storage"
        )


async def save_to_local(
    image: Image.Image,
    img_format: str,
    filename: str,
    subfolder: str = "profile_pictures"
) -> str:
    """
    Save image to local storage.

    Args:
        image: PIL Image object
        img_format: Image format (JPEG, PNG, etc.)
        filename: Filename to save as
        subfolder: Subfolder within uploads directory

    Returns:
        Local file URL path
    """
    try:
        upload_dir = os.path.join("uploads", subfolder)
        os.makedirs(upload_dir, exist_ok=True)

        file_path = os.path.join(upload_dir, filename)
        image.save(file_path, format=img_format, quality=85, optimize=True)

        # Return URL path
        image_url = f"/static/{subfolder}/{filename}"
        logger.info(f"Image saved locally: {image_url}")
        return image_url

    except Exception as e:
        logger.error(f"Local save failed: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save image to local storage"
        )


async def save_profile_picture(file: UploadFile, user_id: str) -> Optional[str]:
    """
    Save and process profile picture.
    Uses Cloudinary if enabled, otherwise falls back to local storage.

    Args:
        file: Uploaded image file
        user_id: User ID for unique naming

    Returns:
        URL to saved image, or None if failed

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
                detail=f"File size exceeds {settings.MAX_UPLOAD_SIZE_MB}MB limit"
            )

        # Process image
        image, img_format = process_image(content)

        # Generate unique identifier
        unique_id = f"{user_id}_{uuid.uuid4().hex}"

        # Upload based on configuration
        if settings.USE_CLOUDINARY and settings.CLOUDINARY_CLOUD_NAME:
            folder = f"{settings.CLOUDINARY_FOLDER}/profile_pictures"
            image_url = await upload_to_cloudinary(image, img_format, folder, unique_id)
        else:
            file_ext = os.path.splitext(file.filename)[1].lower()
            filename = f"{unique_id}{file_ext}"
            image_url = await save_to_local(image, img_format, filename, "profile_pictures")

        logger.info(f"Profile picture saved for user {user_id}: {image_url}")
        return image_url

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save profile picture: {str(e)}")
        return None


async def save_portfolio_image(file: UploadFile, artisan_id: str) -> Optional[str]:
    """
    Save portfolio image for artisan.

    Args:
        file: Uploaded image file
        artisan_id: Artisan ID for unique naming

    Returns:
        URL to saved image, or None if failed
    """
    try:
        # Validate file
        validate_image_file(file)

        # Read file content
        content = await file.read()

        # Check file size (allow larger files for portfolio - up to 10MB)
        max_portfolio_size = 10 * 1024 * 1024  # 10MB
        if len(content) > max_portfolio_size:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"File size exceeds 10MB limit for portfolio images"
            )

        # Process image (larger dimensions for portfolio)
        image, img_format = process_image(content, max_dimension=1920)

        # Generate unique identifier
        unique_id = f"{artisan_id}_{uuid.uuid4().hex}"

        # Upload based on configuration
        if settings.USE_CLOUDINARY and settings.CLOUDINARY_CLOUD_NAME:
            folder = f"{settings.CLOUDINARY_FOLDER}/portfolio"
            image_url = await upload_to_cloudinary(image, img_format, folder, unique_id)
        else:
            file_ext = os.path.splitext(file.filename)[1].lower()
            filename = f"{unique_id}{file_ext}"
            image_url = await save_to_local(image, img_format, filename, "portfolio")

        logger.info(f"Portfolio image saved for artisan {artisan_id}: {image_url}")
        return image_url

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Failed to save portfolio image: {str(e)}")
        return None


async def delete_image(image_url: str) -> bool:
    """
    Delete image from storage (Cloudinary or local).

    Args:
        image_url: URL or path to image

    Returns:
        True if deleted successfully
    """
    try:
        # Check if it's a Cloudinary URL
        if "cloudinary.com" in image_url:
            # Extract public_id from URL
            # Format: https://res.cloudinary.com/{cloud_name}/image/upload/{transformations}/{public_id}.{format}
            parts = image_url.split("/")
            if "upload" in parts:
                upload_index = parts.index("upload")
                # Get everything after 'upload', join and remove extension
                public_id_parts = parts[upload_index + 1:]
                # Skip transformation parameters (v{number})
                public_id_parts = [p for p in public_id_parts if not p.startswith('v')]
                public_id = '/'.join(public_id_parts)
                # Remove extension
                public_id = os.path.splitext(public_id)[0]

                # Delete from Cloudinary
                result = cloudinary.uploader.destroy(public_id)
                success = result.get('result') == 'ok'
                logger.info(f"Deleted image from Cloudinary: {public_id}, success: {success}")
                return success

        # Assume local file
        else:
            # Convert URL path to filesystem path
            # /static/profile_pictures/file.jpg -> uploads/profile_pictures/file.jpg
            file_path = image_url.replace("/static/", "uploads/")
            if os.path.exists(file_path):
                os.remove(file_path)
                logger.info(f"Deleted local image: {file_path}")
                return True
            else:
                logger.warning(f"Local file not found: {file_path}")
                return False

    except Exception as e:
        logger.error(f"Failed to delete image {image_url}: {str(e)}")
        return False
