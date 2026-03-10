"""
Service and Service Category endpoints.
"""
from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy.orm import Session
from typing import List

from app.db.session import get_db
from app.db.models.service_category import ServiceCategory
from app.db.models.service import Service
from app.schemas.service import (
    ServiceCategoryResponse,
    ServiceCategoryWithServicesResponse,
    ServiceResponse,
    ServiceWithCategoryResponse,
)
from app.core.logger import logger


router = APIRouter()


@router.get("/categories", response_model=List[ServiceCategoryResponse])
def get_service_categories(
    skip: int = 0,
    limit: int = 100,
    active_only: bool = True,
    db: Session = Depends(get_db)
):
    """
    Get list of service categories.

    Query Parameters:
    - skip: Number of records to skip (pagination)
    - limit: Maximum number of records to return
    - active_only: Filter only active categories (default: true)
    """
    try:
        query = db.query(ServiceCategory)

        if active_only:
            query = query.filter(ServiceCategory.is_active == True)

        categories = query.order_by(ServiceCategory.display_order, ServiceCategory.name)\
            .offset(skip)\
            .limit(limit)\
            .all()

        logger.info(f"Retrieved {len(categories)} service categories")
        return categories

    except Exception as e:
        logger.error(f"Error fetching service categories: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch service categories"
        )


@router.get("/categories/{category_id}", response_model=ServiceCategoryWithServicesResponse)
def get_service_category(
    category_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a specific service category with its services.
    """
    try:
        category = db.query(ServiceCategory)\
            .filter(ServiceCategory.id == category_id)\
            .first()

        if not category:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service category with id {category_id} not found"
            )

        logger.info(f"Retrieved service category: {category.name}")
        return category

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching service category {category_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch service category"
        )


@router.get("", response_model=List[ServiceWithCategoryResponse])
def get_services(
    skip: int = 0,
    limit: int = 100,
    category_id: int = None,
    include_uncategorized: bool = False,
    db: Session = Depends(get_db)
):
    """
    Get list of services.

    Query Parameters:
    - skip: Number of records to skip (pagination)
    - limit: Maximum number of records to return
    - category_id: Filter by category ID (optional)
    - include_uncategorized: Include legacy uncategorized services (default: false)
    """
    try:
        query = db.query(Service)

        if category_id:
            query = query.filter(Service.category_id == category_id)
        elif not include_uncategorized:
            # Hide legacy records from client apps while preserving historical references.
            query = query.filter(Service.category_id.isnot(None))

        services = query.order_by(Service.name)\
            .offset(skip)\
            .limit(limit)\
            .all()

        logger.info(f"Retrieved {len(services)} services")
        return services

    except Exception as e:
        logger.error(f"Error fetching services: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch services"
        )


@router.get("/{service_id}", response_model=ServiceWithCategoryResponse)
def get_service(
    service_id: int,
    db: Session = Depends(get_db)
):
    """
    Get a specific service by ID.
    """
    try:
        service = db.query(Service)\
            .filter(Service.id == service_id)\
            .first()

        if not service:
            raise HTTPException(
                status_code=status.HTTP_404_NOT_FOUND,
                detail=f"Service with id {service_id} not found"
            )

        logger.info(f"Retrieved service: {service.name}")
        return service

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error fetching service {service_id}: {str(e)}")
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to fetch service"
        )
