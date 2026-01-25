# Infrastructure Setup - Complete ✅

**Date:** January 20, 2026
**Phase:** 0 - Infrastructure Setup
**Status:** COMPLETED

---

## Summary

Successfully set up the core infrastructure for the Workchop backend API, including background task processing, geospatial capabilities, cloud file storage, and email service.

---

## 1. Celery Background Tasks ✅

### What Was Done:
- **Celery Configuration**: Created `app/celery_app.py` with Redis as broker/backend
- **Email Tasks**: Implemented asynchronous email sending tasks
  - `send_otp_email` - Send verification/reset OTPs
  - `send_password_reset_email` - Password reset notifications
  - `send_welcome_email` - Welcome emails for new users
  - `cleanup_expired_otps` - Periodic cleanup (runs hourly)
- **Notification Tasks**: Placeholder tasks for FCM (to be implemented later)
- **Docker Integration**: Added `celery_worker` and `celery_beat` services to docker-compose

### Celery Configuration:
```python
- Task serialization: JSON
- Timezone: UTC
- Task time limit: 5 minutes
- Soft time limit: 4.5 minutes
- Retry with exponential backoff
- Result expiry: 1 hour
```

### How to Run:
```bash
# Start Celery worker
poetry run celery -A app.celery_app worker --loglevel=info

# Start Celery Beat (periodic tasks)
poetry run celery -A app.celery_app beat --loglevel=info

# Or use Docker Compose (recommended)
docker-compose up celery_worker celery_beat
```

### Files Created:
- `app/celery_app.py`
- `app/tasks/__init__.py`
- `app/tasks/email_tasks.py`
- `app/tasks/notification_tasks.py`

---

## 2. PostGIS for Location Services ✅

### What Was Done:
- **Docker Image**: Updated to `postgis/postgis:15-3.4` for spatial data support
- **Alembic Migration**: Created migration to enable PostGIS extensions
  - `postgis` - Core spatial extension
  - `postgis_topology` - Topology support
  - `postgis_raster` - Raster support
- **GeoAlchemy2**: Added for SQLAlchemy PostGIS integration
- **Location Utilities**: Created comprehensive location helper functions

### Location Utilities (`app/utils/location.py`):
```python
- create_point(lat, lng) - Create PostGIS POINT
- calculate_distance_km() - Haversine distance calculation
- distance_query() - SQLAlchemy distance query expression
- within_radius_filter() - Find points within radius
- parse_coordinates() - Parse lat/lng strings
- validate_coordinates() - Validate coordinate ranges
- get_city_coordinates() - Nigerian cities reference
```

### Migration:
```bash
# Run the PostGIS migration
poetry run alembic upgrade head
```

### Files Created/Modified:
- `alembic/versions/b5aaeec89a89_enable_postgis_extension.py`
- `app/utils/location.py`
- Modified: `docker-compose.yml` (PostgreSQL → PostGIS)
- Added: `geoalchemy2==0.15.2` to pyproject.toml

---

## 3. Cloudinary File Upload Integration ✅

### What Was Done:
- **Cloudinary SDK**: Integrated cloudinary Python package
- **Hybrid Storage**: Supports both local and cloud storage
- **Smart Fallback**: Auto-falls back to local if Cloudinary not configured
- **Image Processing**: Resize, optimize, and format conversion
- **Multiple Use Cases**: Profile pictures AND portfolio images

### Features:
```python
- Image validation (type, size, content)
- Automatic resizing (1080x1080 for profiles, 1920x1920 for portfolio)
- RGBA to RGB conversion for JPEG compatibility
- Quality optimization (85%, optimized)
- Unique filename generation
- Cloudinary folder organization (workchop/profile_pictures, workchop/portfolio)
- Delete support for both Cloudinary and local files
```

### Configuration Added:
```env
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
CLOUDINARY_FOLDER=workchop
USE_CLOUDINARY=true
MAX_UPLOAD_SIZE_MB=5
```

### Functions Available:
```python
- save_profile_picture(file, user_id) - Save profile image
- save_portfolio_image(file, artisan_id) - Save portfolio image
- delete_image(image_url) - Delete from Cloudinary or local
- upload_to_cloudinary() - Direct Cloudinary upload
- save_to_local() - Local storage fallback
```

### Files Modified:
- `app/utils/file_upload.py` (complete rewrite)
- `app/core/config.py` (added Cloudinary settings)
- `.env.example` (added Cloudinary variables)
- Added: `cloudinary==1.41.0` to pyproject.toml

---

## 4. Email Service with HTML Templates ✅

### What Was Done:
- **SMTP Implementation**: Real email sending with SMTP support
- **HTML Templates**: Beautiful responsive email templates using Jinja2
- **Graceful Fallback**: Logs emails in development when SMTP not configured
- **Multiple Email Types**: OTP, Password Reset, Welcome, Booking Notifications

### Email Templates Created:
1. **`otp.html`** - Email verification OTPs
   - Clean, modern design
   - Large OTP code display
   - Security warnings
   - 10-minute expiry notice

2. **`password_reset.html`** - Password reset OTPs
   - Red theme for urgency
   - Security alert messaging
   - Large reset code display

3. **`welcome.html`** - Welcome emails for new users
   - Friendly onboarding message
   - Feature highlights
   - Call-to-action button

### Email Functions:
```python
- send_otp_email(email, otp_code, purpose) - OTP emails
- send_password_reset_email(email, reset_token) - Password resets
- send_welcome_email(email, full_name) - Welcome emails
- send_booking_notification(email, ...) - Booking status updates
- send_email_smtp(to_email, subject, html, text) - Core SMTP function
```

### Features:
- Jinja2 template rendering
- HTML + plain text fallback
- SMTP with TLS support
- Configurable sender name/email
- Development mode logging

### Files Created/Modified:
- `app/templates/emails/otp.html`
- `app/templates/emails/password_reset.html`
- `app/templates/emails/welcome.html`
- `app/utils/email.py` (complete rewrite)

---

## Dependencies Added

Updated `pyproject.toml` with:
```toml
celery = "5.4.0"
cloudinary = "1.41.0"
geoalchemy2 = "0.15.2"
```

All installed successfully with Python 3.11.

---

## Docker Compose Updates

Added new services:
```yaml
services:
  db:
    image: postgis/postgis:15-3.4  # Changed from postgres:15

  celery_worker:
    command: celery -A app.celery_app worker --loglevel=info

  celery_beat:
    command: celery -A app.celery_app beat --loglevel=info
```

---

## Environment Variables Required

Update your `.env` file with:

```env
# Redis (required for Celery)
REDIS_URL=redis://localhost:6379/0

# SMTP Email (optional - logs in dev mode if not configured)
SMTP_HOST=smtp.gmail.com
SMTP_PORT=587
SMTP_TLS=true
SMTP_USER=your-email@gmail.com
SMTP_PASSWORD=your-app-password
EMAILS_FROM_EMAIL=noreply@workchop.ng
EMAILS_FROM_NAME=Workchop

# Cloudinary (optional - falls back to local storage)
CLOUDINARY_CLOUD_NAME=your-cloud-name
CLOUDINARY_API_KEY=your-api-key
CLOUDINARY_API_SECRET=your-api-secret
CLOUDINARY_FOLDER=workchop
USE_CLOUDINARY=true
MAX_UPLOAD_SIZE_MB=5
```

---

## Testing the Infrastructure

### 1. Test Celery:
```bash
# Start all services
docker-compose up -d

# Check Celery worker logs
docker logs workchop-api_celery_worker

# Should see: "celery@... ready"
```

### 2. Test PostGIS:
```bash
# Run migrations
poetry run alembic upgrade head

# Connect to database
docker exec -it workchop-api_db psql -U user -d workchop_db

# Test PostGIS
workchop_db=# SELECT PostGIS_Version();
# Should return PostGIS version
```

### 3. Test Email:
```python
from app.utils.email import send_otp_email

# In development (no SMTP), this will log the email
result = send_otp_email("test@example.com", "123456", "verification")
# Check logs for email preview
```

### 4. Test Cloudinary:
```python
from app.utils.file_upload import save_profile_picture

# Upload test image
# If Cloudinary not configured, falls back to local storage
```

---

## What's Next?

Phase 0 is complete! Ready to proceed with:

**Phase 1: Service Categories & Profile Management**
- Create service category models
- Implement artisan/customer profile endpoints
- Add portfolio management
- Profile image uploads (now with Cloudinary!)

**Phase 2: Location & Search**
- Artisan location tracking (now with PostGIS!)
- Proximity-based search
- Radius filtering

**Phase 3: Booking System**
- Booking flow implementation
- Status management
- Email notifications (now ready!)

---

## Notes

- **Development Mode**: Email service logs emails instead of sending when SMTP not configured
- **Cloudinary**: Optional - system works with local storage if not configured
- **PostGIS**: Required for location features - migration must be run
- **Celery**: Required for async tasks - Redis must be running

---

**Infrastructure is battle-ready! 🚀**

Let's proceed with implementing the core business logic modules.
