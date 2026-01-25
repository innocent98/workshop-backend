# Frontend API Documentation - Workchop Backend

**Base URL:** `http://localhost:8000/api/v1`
**Production URL:** TBD

All endpoints return JSON unless otherwise specified.

---

## Authentication Module

### 1. Registration Flow (5 Steps)

#### Step 1: Submit Personal Information

**Endpoint:** `POST /auth/register/personal-info`

**Request Body:**
```json
{
  "full_name": "John Doe",
  "email": "john.doe@example.com",
  "phone_number": "08012345678",
  "user_type": "artisan"
}
```

**Field Requirements:**
- `full_name`: Required, string
- `email`: Required, valid email format, must be unique
- `phone_number`: Required, string, must be unique
- `user_type`: Required, enum: `"artisan"` or `"client"`

**Success Response (201):**
```json
{
  "message": "Personal information saved successfully",
  "user_id": "123e4567-e89b-12d3-a456-426614174000"
}
```

**Error Responses:**
- **400** - Validation error (invalid email, missing fields, etc.)
- **409** - Email or phone number already exists
```json
{
  "detail": "Email already registered"
}
```

---

#### Step 2: Set Password

**Endpoint:** `POST /auth/register/password`

**Request Body:**
```json
{
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "password": "SecurePass123!",
  "confirm_password": "SecurePass123!"
}
```

**Field Requirements:**
- `user_id`: Required, UUID string from Step 1
- `password`: Required, minimum 8 characters
- `confirm_password`: Required, must match password

**Success Response (200):**
```json
{
  "message": "Password set successfully"
}
```

**Error Responses:**
- **400** - Passwords don't match or too short
- **404** - User ID not found

---

#### Step 3a: Send OTP for Verification

**Endpoint:** `POST /auth/register/send-otp`

**Request Body:**
```json
{
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "email": "john.doe@example.com"
}
```

**Field Requirements:**
- `user_id`: Required, UUID string
- `email`: Required, must match user's email

**Success Response (200):**
```json
{
  "message": "OTP sent successfully to john.doe@example.com"
}
```

**Implementation Notes:**
- Generates 6-digit numeric OTP
- OTP expires in 10 minutes
- Invalidates any previous unused OTPs for this user
- Email is sent to the provided address (check your inbox)

**Error Responses:**
- **404** - User not found or email mismatch

---

#### Step 3b: Verify OTP

**Endpoint:** `POST /auth/register/verify-otp`

**Request Body:**
```json
{
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "otp_code": "123456"
}
```

**Field Requirements:**
- `user_id`: Required, UUID string
- `otp_code`: Required, 6-digit string

**Success Response (200):**
```json
{
  "message": "OTP verified successfully"
}
```

**Error Responses:**
- **400** - Invalid or expired OTP
```json
{
  "detail": "Invalid or expired OTP"
}
```
- **404** - User not found or no OTP sent

---

#### Step 4: Select Services

**Endpoint:** `POST /auth/register/services`

**Request Body:**
```json
{
  "user_id": "123e4567-e89b-12d3-a456-426614174000",
  "user_type": "artisan",
  "services": [1, 3, 5]
}
```

**Field Requirements:**
- `user_id`: Required, UUID string
- `user_type`: Required, enum: `"artisan"` or `"client"`
- `services`: Required, array of service IDs (integers), at least one service

**Success Response (200):**
```json
{
  "message": "Services selected successfully"
}
```

**Implementation Notes:**
- Service IDs must exist in the database
- Creates many-to-many relationships between user and services
- Multiple services can be selected

**Error Responses:**
- **400** - Empty services array or invalid service IDs
- **404** - User not found or service ID doesn't exist

---

#### Step 5: Complete Profile

**Endpoint:** `POST /auth/register/profile`

**Content-Type:** `multipart/form-data`

**Form Fields:**
- `user_id`: Required, UUID string
- `bio`: Optional, text
- `profile_picture`: Optional, image file (JPEG, PNG, GIF)

**Example (using FormData):**
```javascript
const formData = new FormData();
formData.append('user_id', '123e4567-e89b-12d3-a456-426614174000');
formData.append('bio', 'Experienced plumber with 10 years experience');
formData.append('profile_picture', imageFile); // File object
```

**File Requirements:**
- Max size: 5MB
- Formats: JPEG, PNG, GIF only
- Image is automatically resized to max 1080x1080 pixels
- Image is compressed and optimized

**Success Response (200):**
```json
{
  "message": "Profile completed successfully",
  "profile_picture_url": "/static/profile_pictures/123e4567_a1b2c3d4.jpg"
}
```

**Implementation Notes:**
- Sets `registration_completed = true` on the user
- Sends a welcome email to the user
- Profile picture is optional; bio is optional
- Without profile picture, user can still complete registration

**Error Responses:**
- **400** - Invalid file format or file too large
```json
{
  "detail": "File size exceeds 5MB limit"
}
```
- **404** - User not found

---

### 2. Login

#### Standard Login

**Endpoint:** `POST /auth/login`

**Request Body:**
```json
{
  "email": "john.doe@example.com",
  "password": "SecurePass123!"
}
```

**Field Requirements:**
- `email`: Required, valid email format
- `password`: Required

**Success Response (200):**
```json
{
  "access_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "token_type": "bearer",
  "user": {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "full_name": "John Doe",
    "email": "john.doe@example.com",
    "phone_number": "08012345678",
    "user_type": "artisan",
    "profile_picture_url": "/static/profile_pictures/123e4567_a1b2c3d4.jpg",
    "bio": "Experienced plumber with 10 years experience",
    "is_email_verified": true,
    "is_active": true,
    "registration_completed": true,
    "created_at": "2025-01-19T10:30:00Z"
  }
}
```

**Token Usage:**
- Include in subsequent requests as: `Authorization: Bearer {access_token}`
- Token expires in 7 days (configurable)
- Token contains user_id in the payload

**Error Responses:**
- **401** - Invalid credentials
```json
{
  "detail": "Incorrect email or password"
}
```
- **403** - Account issues
```json
{
  "detail": "Account is not active"
}
```
OR
```json
{
  "detail": "Please complete your registration"
}
```

---

#### Google Sign-In

**Endpoint:** `POST /auth/google`

**Status:** NOT IMPLEMENTED

**Request Body:**
```json
{
  "google_token": "google_oauth_token_here",
  "user_type": "artisan"
}
```

**Current Response (501):**
```json
{
  "detail": "Google sign-in not yet implemented"
}
```

**Planned Behavior:**
- Will verify Google token
- Create new user if doesn't exist
- Link Google ID to existing user if email matches
- Return JWT token + user info (same as standard login)

---

### 3. Password Recovery Flow (3 Steps)

#### Step 1: Send Reset Code

**Endpoint:** `POST /auth/forgot-password/send-code`

**Request Body:**
```json
{
  "email": "john.doe@example.com"
}
```

**Field Requirements:**
- `email`: Required, valid email format

**Success Response (200):**
```json
{
  "message": "If the email exists, a reset code has been sent"
}
```

**Implementation Notes:**
- Always returns success message (security best practice)
- Generates 6-digit OTP
- OTP expires in 10 minutes
- Email is sent with the reset code

---

#### Step 2: Verify Reset Code

**Endpoint:** `POST /auth/forgot-password/verify-code`

**Request Body:**
```json
{
  "email": "john.doe@example.com",
  "code": "123456"
}
```

**Field Requirements:**
- `email`: Required, valid email format
- `code`: Required, 6-digit string

**Success Response (200):**
```json
{
  "message": "Code verified successfully",
  "reset_token": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6"
}
```

**Implementation Notes:**
- `reset_token` is a 32-character URL-safe token
- Token expires in 30 minutes
- Save this token for Step 3

**Error Responses:**
- **400** - Invalid or expired code
```json
{
  "detail": "Invalid or expired reset code"
}
```

---

#### Step 3: Reset Password

**Endpoint:** `POST /auth/forgot-password/reset`

**Request Body:**
```json
{
  "email": "john.doe@example.com",
  "reset_token": "a1b2c3d4e5f6g7h8i9j0k1l2m3n4o5p6",
  "new_password": "NewSecurePass123!",
  "confirm_password": "NewSecurePass123!"
}
```

**Field Requirements:**
- `email`: Required, valid email format
- `reset_token`: Required, token from Step 2
- `new_password`: Required, minimum 8 characters
- `confirm_password`: Required, must match new_password

**Success Response (200):**
```json
{
  "message": "Password reset successfully"
}
```

**Implementation Notes:**
- Token is marked as used after successful reset
- User must login again with new password

**Error Responses:**
- **400** - Passwords don't match, invalid token, or token expired
```json
{
  "detail": "Invalid or expired reset token"
}
```

---

### 4. Utility Endpoints

#### Resend OTP

**Endpoint:** `POST /auth/resend-otp`

**Request Body:**
```json
{
  "email": "john.doe@example.com",
  "type": "phone_verification"
}
```

**Field Requirements:**
- `email`: Required, valid email format
- `type`: Required, enum: `"phone_verification"` or `"password_reset"`

**Success Response (200):**
```json
{
  "message": "If the email exists, a new OTP has been sent"
}
```

**Implementation Notes:**
- Always returns success (security best practice)
- Invalidates previous OTPs
- Generates new 6-digit OTP
- OTP expires in 10 minutes

---

## Common Error Responses

All endpoints may return these standard errors:

**422 - Validation Error:**
```json
{
  "detail": [
    {
      "type": "string_too_short",
      "loc": ["body", "password"],
      "msg": "String should have at least 8 characters",
      "input": "short",
      "ctx": { "min_length": 8 }
    }
  ]
}
```

**500 - Internal Server Error:**
```json
{
  "detail": "Internal server error"
}
```

---

## Notes for Frontend Implementation

1. **Token Storage:** Store the `access_token` securely (e.g., HttpOnly cookies or secure storage)
2. **Token Expiry:** Token expires in 7 days. Implement refresh logic or re-login
3. **File Uploads:** Use `multipart/form-data` for profile picture upload
4. **OTP Expiry:** OTPs expire in 10 minutes. Show countdown timer
5. **Reset Token Expiry:** Reset tokens expire in 30 minutes
6. **Registration Flow:** All 5 steps must be completed in order
7. **User Types:** Only `"artisan"` and `"client"` are valid user types

---

## Services Module

### 1. Get Service Categories

**Endpoint:** `GET /services/categories`

**Query Parameters:**
- `skip`: Optional, integer (default: 0) - Number of records to skip for pagination
- `limit`: Optional, integer (default: 100) - Maximum number of records to return
- `active_only`: Optional, boolean (default: true) - Filter only active categories

**Success Response (200):**
```json
[
  {
    "id": 1,
    "name": "Plumbing",
    "description": "All plumbing related services",
    "icon": "🔧",
    "is_active": true,
    "display_order": 1,
    "created_at": "2025-01-20T10:00:00Z"
  },
  {
    "id": 2,
    "name": "Electrical",
    "description": "Electrical installation and repair",
    "icon": "⚡",
    "is_active": true,
    "display_order": 2,
    "created_at": "2025-01-20T10:00:00Z"
  }
]
```

**Error Responses:**
- **500** - Internal server error

---

### 2. Get Service Category with Services

**Endpoint:** `GET /services/categories/{category_id}`

**Path Parameters:**
- `category_id`: Required, integer - The category ID

**Success Response (200):**
```json
{
  "id": 1,
  "name": "Plumbing",
  "description": "All plumbing related services",
  "icon": "🔧",
  "is_active": true,
  "display_order": 1,
  "created_at": "2025-01-20T10:00:00Z",
  "services": [
    {
      "id": 1,
      "name": "Pipe Repair",
      "description": "Fix leaking or broken pipes",
      "category_id": 1,
      "created_at": "2025-01-20T10:00:00Z"
    },
    {
      "id": 2,
      "name": "Bathroom Installation",
      "description": "Install bathroom fixtures",
      "category_id": 1,
      "created_at": "2025-01-20T10:00:00Z"
    }
  ]
}
```

**Error Responses:**
- **404** - Category not found
```json
{
  "detail": "Service category with id 999 not found"
}
```

---

### 3. Get Services

**Endpoint:** `GET /services`

**Query Parameters:**
- `skip`: Optional, integer (default: 0) - Number of records to skip for pagination
- `limit`: Optional, integer (default: 100) - Maximum number of records to return
- `category_id`: Optional, integer - Filter services by category ID

**Success Response (200):**
```json
[
  {
    "id": 1,
    "name": "Pipe Repair",
    "description": "Fix leaking or broken pipes",
    "category_id": 1,
    "created_at": "2025-01-20T10:00:00Z",
    "category": {
      "id": 1,
      "name": "Plumbing",
      "description": "All plumbing related services",
      "icon": "🔧",
      "is_active": true,
      "display_order": 1,
      "created_at": "2025-01-20T10:00:00Z"
    }
  }
]
```

**Error Responses:**
- **500** - Internal server error

---

### 4. Get Service by ID

**Endpoint:** `GET /services/{service_id}`

**Path Parameters:**
- `service_id`: Required, integer - The service ID

**Success Response (200):**
```json
{
  "id": 1,
  "name": "Pipe Repair",
  "description": "Fix leaking or broken pipes",
  "category_id": 1,
  "created_at": "2025-01-20T10:00:00Z",
  "category": {
    "id": 1,
    "name": "Plumbing",
    "description": "All plumbing related services",
    "icon": "🔧",
    "is_active": true,
    "display_order": 1,
    "created_at": "2025-01-20T10:00:00Z"
  }
}
```

**Error Responses:**
- **404** - Service not found
```json
{
  "detail": "Service with id 999 not found"
}
```

---

## Profiles Module

**Authentication Required:** All profile endpoints require JWT token in Authorization header:
```
Authorization: Bearer {access_token}
```

### 1. Customer Profile

#### Get My Customer Profile

**Endpoint:** `GET /profiles/customers/me`

**Headers:**
- `Authorization`: Required, Bearer token

**Success Response (200):**
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "full_name": "Jane Smith",
  "email": "jane@example.com",
  "phone_number": "08012345678",
  "profile_picture_url": "/static/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Looking for reliable artisans",
  "is_email_verified": true,
  "is_active": true,
  "created_at": "2025-01-20T10:00:00Z"
}
```

**Error Responses:**
- **401** - Unauthorized (invalid or missing token)
- **403** - User account is inactive

---

#### Update My Customer Profile

**Endpoint:** `PUT /profiles/customers/me`

**Headers:**
- `Authorization`: Required, Bearer token

**Request Body:**
```json
{
  "full_name": "Jane Smith Updated",
  "phone_number": "08087654321",
  "bio": "Updated bio text"
}
```

**Field Requirements:**
- `full_name`: Optional, string (1-255 characters)
- `phone_number`: Optional, string (10-20 characters), must be unique
- `bio`: Optional, string (max 1000 characters)

**Success Response (200):**
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "full_name": "Jane Smith Updated",
  "email": "jane@example.com",
  "phone_number": "08087654321",
  "profile_picture_url": "/static/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Updated bio text",
  "is_email_verified": true,
  "is_active": true,
  "created_at": "2025-01-20T10:00:00Z"
}
```

**Error Responses:**
- **400** - Phone number already registered
- **401** - Unauthorized
- **500** - Failed to update profile

---

### 2. Artisan Profile

#### Get My Artisan Profile

**Endpoint:** `GET /profiles/artisans/me`

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to users with `user_type: "artisan"`

**Success Response (200):**
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "full_name": "John Doe",
  "email": "john@example.com",
  "phone_number": "08012345678",
  "profile_picture_url": "/static/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Experienced plumber with 10 years",
  "user_type": "artisan",
  "location_address": "123 Main St, Lagos",
  "service_radius_km": 15.0,
  "hourly_rate_min": 5000,
  "hourly_rate_max": 15000,
  "years_of_experience": 10,
  "specialization": "Residential plumbing",
  "is_verified": true,
  "verified_at": "2025-01-15T12:00:00Z",
  "availability_status": "available",
  "average_rating": 4.5,
  "total_ratings": 25,
  "total_jobs_completed": 30,
  "response_time_avg_minutes": 45,
  "acceptance_rate": 0.85,
  "created_at": "2025-01-10T10:00:00Z"
}
```

**Implementation Notes:**
- If artisan profile doesn't exist, it will be created automatically
- Returns private view with all details including email

**Error Responses:**
- **401** - Unauthorized
- **403** - Only artisans can access this endpoint

---

#### Update My Artisan Profile

**Endpoint:** `PUT /profiles/artisans/me`

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to artisans

**Request Body:**
```json
{
  "location": {
    "latitude": 6.5244,
    "longitude": 3.3792,
    "address": "123 Main St, Lagos"
  },
  "location_address": "123 Main St, Lagos",
  "service_radius_km": 15,
  "hourly_rate_min": 5000,
  "hourly_rate_max": 15000,
  "years_of_experience": 10,
  "specialization": "Residential plumbing"
}
```

**Field Requirements:**
- `location`: Optional, object with:
  - `latitude`: Required if location provided, number (-90 to 90)
  - `longitude`: Required if location provided, number (-180 to 180)
  - `address`: Optional, string (max 500 characters)
- `location_address`: Optional, string (max 500 characters)
- `service_radius_km`: Optional, number (1 to 100)
- `hourly_rate_min`: Optional, decimal (>= 0)
- `hourly_rate_max`: Optional, decimal (>= hourly_rate_min)
- `years_of_experience`: Optional, integer (0 to 50)
- `specialization`: Optional, string (max 200 characters)

**Success Response (200):**
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "full_name": "John Doe",
  "email": "john@example.com",
  "phone_number": "08012345678",
  "profile_picture_url": "/static/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Experienced plumber with 10 years",
  "user_type": "artisan",
  "location_address": "123 Main St, Lagos",
  "service_radius_km": 15.0,
  "hourly_rate_min": 5000,
  "hourly_rate_max": 15000,
  "years_of_experience": 10,
  "specialization": "Residential plumbing",
  "is_verified": true,
  "verified_at": "2025-01-15T12:00:00Z",
  "availability_status": "available",
  "average_rating": 4.5,
  "total_ratings": 25,
  "total_jobs_completed": 30,
  "response_time_avg_minutes": 45,
  "acceptance_rate": 0.85,
  "created_at": "2025-01-10T10:00:00Z"
}
```

**Error Responses:**
- **403** - Only artisans can access this endpoint
- **422** - Validation error (e.g., hourly_rate_max < hourly_rate_min)
- **500** - Failed to update profile

---

#### Toggle Artisan Availability

**Endpoint:** `PATCH /profiles/artisans/me/availability`

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to artisans

**Request Body:**
```json
{
  "availability_status": "busy"
}
```

**Field Requirements:**
- `availability_status`: Required, enum: `"available"`, `"busy"`, or `"offline"`

**Success Response (200):**
Returns full artisan profile (same as GET /profiles/artisans/me)

**Error Responses:**
- **403** - Only artisans can access this endpoint
- **500** - Failed to update availability

---

#### Get My Artisan Statistics

**Endpoint:** `GET /profiles/artisans/me/stats`

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to artisans

**Success Response (200):**
```json
{
  "average_rating": 4.5,
  "total_ratings": 25,
  "total_jobs_completed": 30,
  "response_time_avg_minutes": 45,
  "acceptance_rate": 0.85
}
```

**Implementation Notes:**
- If no artisan profile exists, returns default stats (all zeros)

**Error Responses:**
- **403** - Only artisans can access this endpoint

---

#### Get Artisan Public Profile

**Endpoint:** `GET /profiles/artisans/{artisan_id}`

**Path Parameters:**
- `artisan_id`: Required, UUID string - The artisan's user ID

**Access:** Available to all users (no authentication required)

**Success Response (200):**
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "full_name": "John Doe",
  "profile_picture_url": "/static/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Experienced plumber with 10 years",
  "location_address": "123 Main St, Lagos",
  "service_radius_km": 15.0,
  "hourly_rate_min": 5000,
  "hourly_rate_max": 15000,
  "years_of_experience": 10,
  "specialization": "Residential plumbing",
  "is_verified": true,
  "availability_status": "available",
  "average_rating": 4.5,
  "total_ratings": 25,
  "total_jobs_completed": 30,
  "response_time_avg_minutes": 45
}
```

**Implementation Notes:**
- Returns public view only (no email, phone number, or private details)
- Email and sensitive information are excluded

**Error Responses:**
- **400** - User is not an artisan
- **404** - Artisan not found
- **500** - Failed to fetch profile

---

### 3. Portfolio Management

#### Get My Portfolio

**Endpoint:** `GET /profiles/artisans/me/portfolio`

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to artisans

**Success Response (200):**
```json
[
  {
    "id": 1,
    "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
    "image_url": "https://res.cloudinary.com/workchop/portfolio/image1.jpg",
    "title": "Bathroom Renovation",
    "description": "Complete bathroom renovation for residential client",
    "project_date": "2025-01-15T00:00:00Z",
    "display_order": 1,
    "created_at": "2025-01-16T10:00:00Z"
  },
  {
    "id": 2,
    "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
    "image_url": "https://res.cloudinary.com/workchop/portfolio/image2.jpg",
    "title": "Kitchen Plumbing",
    "description": "Installed new kitchen sink and fixtures",
    "project_date": null,
    "display_order": 2,
    "created_at": "2025-01-17T10:00:00Z"
  }
]
```

**Implementation Notes:**
- Returns empty array if no portfolio items
- Sorted by display_order, then created_at (newest first)

**Error Responses:**
- **403** - Only artisans can access this endpoint

---

#### Add Portfolio Item

**Endpoint:** `POST /profiles/artisans/me/portfolio`

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to artisans

**Content-Type:** `multipart/form-data`

**Form Fields:**
- `image`: Required, image file (JPEG, PNG, GIF, WEBP)
- `title`: Optional, string (max 200 characters)
- `description`: Optional, string (max 2000 characters)
- `display_order`: Optional, integer (default: 0)

**Example (using FormData):**
```javascript
const formData = new FormData();
formData.append('image', imageFile); // File object
formData.append('title', 'Bathroom Renovation');
formData.append('description', 'Complete bathroom renovation');
formData.append('display_order', '1');
```

**File Requirements:**
- Max size: 10MB (larger than profile pictures)
- Formats: JPEG, PNG, GIF, WEBP
- Image is automatically resized to max 1920x1920 pixels
- Image is compressed and optimized

**Success Response (201):**
```json
{
  "id": 1,
  "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
  "image_url": "https://res.cloudinary.com/workchop/portfolio/image1.jpg",
  "title": "Bathroom Renovation",
  "description": "Complete bathroom renovation for residential client",
  "project_date": null,
  "display_order": 1,
  "created_at": "2025-01-16T10:00:00Z"
}
```

**Error Responses:**
- **400** - Invalid file format or file too large
- **403** - Only artisans can access this endpoint
- **500** - Failed to upload image or add portfolio item

---

#### Update Portfolio Item

**Endpoint:** `PUT /profiles/artisans/me/portfolio/{item_id}`

**Path Parameters:**
- `item_id`: Required, integer - The portfolio item ID

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to artisans (can only update their own items)

**Request Body:**
```json
{
  "title": "Updated Title",
  "description": "Updated description",
  "project_date": "2025-01-15T00:00:00Z",
  "display_order": 1
}
```

**Field Requirements:**
- `title`: Optional, string (max 200 characters)
- `description`: Optional, string (max 2000 characters)
- `project_date`: Optional, datetime ISO string
- `display_order`: Optional, integer

**Implementation Notes:**
- This endpoint updates metadata only, not the image
- To change the image, delete and create a new portfolio item

**Success Response (200):**
```json
{
  "id": 1,
  "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
  "image_url": "https://res.cloudinary.com/workchop/portfolio/image1.jpg",
  "title": "Updated Title",
  "description": "Updated description",
  "project_date": "2025-01-15T00:00:00Z",
  "display_order": 1,
  "created_at": "2025-01-16T10:00:00Z"
}
```

**Error Responses:**
- **403** - Only artisans can access this endpoint
- **404** - Portfolio item not found
- **500** - Failed to update portfolio item

---

#### Delete Portfolio Item

**Endpoint:** `DELETE /profiles/artisans/me/portfolio/{item_id}`

**Path Parameters:**
- `item_id`: Required, integer - The portfolio item ID

**Headers:**
- `Authorization`: Required, Bearer token

**Access:** Only available to artisans (can only delete their own items)

**Success Response (204):**
No content returned

**Implementation Notes:**
- Deletes both the database record and the image from Cloudinary/storage
- Returns 204 No Content on success

**Error Responses:**
- **403** - Only artisans can access this endpoint
- **404** - Portfolio item not found
- **500** - Failed to delete portfolio item

---

#### Get Artisan Portfolio (Public)

**Endpoint:** `GET /profiles/artisans/{artisan_id}/portfolio`

**Path Parameters:**
- `artisan_id`: Required, UUID string - The artisan's user ID

**Access:** Available to all users (no authentication required)

**Success Response (200):**
```json
[
  {
    "id": 1,
    "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
    "image_url": "https://res.cloudinary.com/workchop/portfolio/image1.jpg",
    "title": "Bathroom Renovation",
    "description": "Complete bathroom renovation for residential client",
    "project_date": "2025-01-15T00:00:00Z",
    "display_order": 1,
    "created_at": "2025-01-16T10:00:00Z"
  }
]
```

**Implementation Notes:**
- Returns empty array if artisan has no portfolio items
- Sorted by display_order, then created_at (newest first)

**Error Responses:**
- **404** - Artisan not found
- **500** - Failed to fetch portfolio

---

## Search Module

### 1. Search Artisans by Location

**Endpoint:** `GET /search/artisans`

**Description:** Search for artisans based on location with proximity-based filtering using PostGIS. Returns artisans within the specified radius sorted by distance or other criteria.

**Query Parameters:**
```
latitude (required): float, -90 to 90
longitude (required): float, -180 to 180
radius_km (optional): float, 0.1 to 100, default: 10.0
category_id (optional): int
service_ids (optional): string (comma-separated IDs, e.g., "1,2,3")
min_hourly_rate (optional): decimal, >= 0
max_hourly_rate (optional): decimal, >= 0
min_rating (optional): float, 0 to 5
verified_only (optional): boolean, default: false
availability_status (optional): string ("available", "busy", "offline")
min_years_experience (optional): int, >= 0
sort_by (optional): string, options: "distance", "rating", "price", "experience", "jobs_completed", "response_time", default: "distance"
sort_order (optional): string, "asc" or "desc", default: "asc"
page (optional): int, >= 1, default: 1
page_size (optional): int, 1 to 100, default: 20
```

**Example Request:**
```
GET /search/artisans?latitude=6.5244&longitude=3.3792&radius_km=15&category_id=1&verified_only=true&min_rating=4.0&sort_by=rating&sort_order=desc&page=1&page_size=10
```

**Success Response (200):**
```json
{
  "results": [
    {
      "id": "123e4567-e89b-12d3-a456-426614174000",
      "full_name": "John Smith",
      "profile_picture": "https://cloudinary.com/profile.jpg",
      "location_address": "123 Main St, Ikeja, Lagos",
      "service_radius_km": 20.0,
      "hourly_rate_min": 5000.00,
      "hourly_rate_max": 15000.00,
      "years_of_experience": 8,
      "specialization": "Commercial and residential plumbing",
      "is_verified": true,
      "availability_status": "available",
      "average_rating": 4.7,
      "total_ratings": 45,
      "total_jobs_completed": 120,
      "response_time_avg_minutes": 15,
      "acceptance_rate": 0.85,
      "distance_km": 2.34,
      "services": ["Pipe Installation", "Leak Repair", "Water Heater"],
      "portfolio_sample": "https://cloudinary.com/portfolio1.jpg"
    }
  ],
  "total": 25,
  "page": 1,
  "page_size": 10,
  "total_pages": 3,
  "search_location": {
    "latitude": 6.5244,
    "longitude": 3.3792
  },
  "filters_applied": {
    "radius_km": 15.0,
    "verified_only": true,
    "category_id": 1,
    "min_rating": 4.0
  }
}
```

**Response Fields:**
- `results`: Array of artisan search results
  - `id`: Artisan user ID (UUID string)
  - `full_name`: Artisan's full name
  - `profile_picture`: URL to profile image or null
  - `location_address`: Human-readable address
  - `service_radius_km`: How far the artisan is willing to travel
  - `hourly_rate_min/max`: Rate range in NGN (can be null)
  - `years_of_experience`: Years of experience (can be null)
  - `specialization`: Artisan's area of specialization
  - `is_verified`: Whether artisan is verified
  - `availability_status`: Current availability
  - `average_rating`: Average rating (0.0 to 5.0)
  - `total_ratings`: Number of ratings received
  - `total_jobs_completed`: Total completed jobs
  - `response_time_avg_minutes`: Average response time in minutes
  - `acceptance_rate`: Job acceptance rate (0.0 to 1.0)
  - `distance_km`: Distance from search location in kilometers
  - `services`: Array of service names offered by artisan
  - `portfolio_sample`: URL to one portfolio image or null
- `total`: Total number of results matching criteria
- `page`: Current page number
- `page_size`: Number of results per page
- `total_pages`: Total number of pages
- `search_location`: The coordinates used for search
- `filters_applied`: Summary of filters used in the search

**Implementation Notes:**
- Uses PostGIS ST_DWithin for efficient spatial queries
- Distance is calculated using ST_Distance and returned in kilometers
- Results are distinct (no duplicate artisans even if they offer multiple services)
- If service_ids or category_id filters are used, only artisans offering those services are returned
- Price filtering considers both min and max hourly rates (shows artisan if rate range overlaps filter)
- Sorting by "price" uses hourly_rate_min
- Pagination starts at page 1

**Error Responses:**
- **400** - Invalid query parameters (e.g., latitude out of range)
```json
{
  "detail": "Latitude must be between -90 and 90"
}
```
- **500** - Database or server error

---

### 2. Get Service Availability

**Endpoint:** `GET /search/services/availability`

**Description:** Get aggregated statistics about service availability in a specific location. Shows which services are available, how many artisans offer each service, and average rates and ratings.

**Query Parameters:**
```
latitude (required): float, -90 to 90
longitude (required): float, -180 to 180
radius_km (optional): float, 0.1 to 100, default: 10.0
category_id (optional): int
```

**Example Request:**
```
GET /search/services/availability?latitude=6.5244&longitude=3.3792&radius_km=20&category_id=1
```

**Success Response (200):**
```json
[
  {
    "service_id": 1,
    "service_name": "Pipe Installation",
    "category_id": 1,
    "category_name": "Plumbing",
    "artisans_available": 12,
    "average_hourly_rate": 8500.50,
    "average_rating": 4.3,
    "closest_artisan_distance_km": 1.25
  },
  {
    "service_id": 2,
    "service_name": "Leak Repair",
    "category_id": 1,
    "category_name": "Plumbing",
    "artisans_available": 15,
    "average_hourly_rate": 7000.00,
    "average_rating": 4.5,
    "closest_artisan_distance_km": 0.85
  }
]
```

**Response Fields:**
- `service_id`: Service ID
- `service_name`: Name of the service
- `category_id`: Category ID
- `category_name`: Category name
- `artisans_available`: Number of available artisans offering this service
- `average_hourly_rate`: Average hourly rate for this service (can be null)
- `average_rating`: Average rating of artisans offering this service (can be null)
- `closest_artisan_distance_km`: Distance to the closest artisan offering this service

**Implementation Notes:**
- Only counts artisans with availability_status = "available"
- Only includes active services
- Results are grouped by service and ordered by category name, then service name
- Statistics are calculated only for artisans within the specified radius
- If no artisans are available for a service, it won't appear in results

**Error Responses:**
- **400** - Invalid query parameters
- **500** - Database or server error

---

### 3. Get Nearby Artisans Summary

**Endpoint:** `GET /search/artisans/nearby/summary`

**Description:** Get summary statistics of artisans in a specific area. Provides a quick overview without returning individual artisan details.

**Query Parameters:**
```
latitude (required): float, -90 to 90
longitude (required): float, -180 to 180
radius_km (optional): float, 0.1 to 100, default: 10.0
```

**Example Request:**
```
GET /search/artisans/nearby/summary?latitude=6.5244&longitude=3.3792&radius_km=25
```

**Success Response (200):**
```json
{
  "total_artisans": 47,
  "total_verified": 32,
  "total_available": 38,
  "services_offered": 28,
  "average_rating": 4.4,
  "distance_range_km": {
    "min": 0.35,
    "max": 24.87
  }
}
```

**Response Fields:**
- `total_artisans`: Total number of artisans in the area
- `total_verified`: Number of verified artisans
- `total_available`: Number of currently available artisans
- `services_offered`: Total number of unique services offered
- `average_rating`: Average rating across all artisans
- `distance_range_km`: Distance range of artisans found
  - `min`: Distance to the closest artisan
  - `max`: Distance to the farthest artisan (within radius)

**Implementation Notes:**
- Useful for showing availability indicators before performing detailed search
- Can be used to determine if it's worth expanding search radius
- All statistics exclude inactive users
- Average rating is calculated across all artisans, not weighted by number of ratings

**Error Responses:**
- **400** - Invalid query parameters
- **500** - Database or server error

---

## Additional Notes for Frontend Implementation

8. **Authentication:** Profile and portfolio endpoints require JWT Bearer token (search endpoints are public)
9. **Availability Status:** Valid values are `"available"`, `"busy"`, `"offline"`
10. **Location:** When updating location, both latitude and longitude are required together
11. **Portfolio Images:** Portfolio images support larger file sizes (10MB vs 5MB for profiles)
12. **Image Dimensions:** Portfolio images are resized to max 1920x1920, profiles to 1080x1080
13. **Public vs Private:** Artisan public profiles exclude email and phone number for privacy
14. **Search Radius:** Default search radius is 10km, maximum is 100km
15. **Coordinates:** Nigeria's approximate coordinates: Lagos (6.5244, 3.3792), Abuja (9.0765, 7.3986), Port Harcourt (4.8156, 7.0498)
16. **Distance Calculation:** All distances use PostGIS ST_Distance on WGS84 geography for accurate results
17. **Search Performance:** Location-based searches are optimized with spatial indexes for fast queries

---

## TODO / Coming Soon

- Google OAuth implementation
- Booking system endpoints
- Payment integration endpoints
- Chat messaging endpoints
- Push notifications endpoints

---

**Last Updated:** 2026-01-21
**API Version:** v1
