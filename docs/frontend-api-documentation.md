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
  "success": true,
  "message": "Personal information submitted successfully",
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
  "success": true,
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
  "success": true,
  "message": "OTP sent successfully to your email"
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
  "success": true,
  "message": "Email verified successfully"
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
  "services": ["Pipe Repair", "Bathroom Installation", "Kitchen Plumbing"]
}
```

**Field Requirements:**
- `user_id`: Required, UUID string
- `user_type`: Required, enum: `"artisan"` or `"client"`
- `services`: Required, array of service names (strings), at least one service

**Success Response (200):**
```json
{
  "success": true,
  "message": "Services selected successfully"
}
```

**Implementation Notes:**
- Service names must exist in the database
- Creates many-to-many relationships between user and services
- Multiple services can be selected
- Services are matched by exact name (case-sensitive)

**Error Responses:**
- **400** - Empty services array, user type mismatch, or invalid UUID
- **404** - User not found or service name doesn't exist

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
  "success": true,
  "message": "Registration completed successfully",
  "user": {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "full_name": "John Doe",
    "email": "john.doe@example.com",
    "phone_number": "08012345678",
    "user_type": "artisan",
    "profile_picture_url": "https://res.cloudinary.com/workchop/profile_pictures/123e4567_a1b2c3d4.jpg",
    "bio": "Experienced plumber with 10 years experience"
  }
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
  "success": true,
  "message": "Login successful",
  "token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9...",
  "user": {
    "id": "123e4567-e89b-12d3-a456-426614174000",
    "full_name": "John Doe",
    "email": "john.doe@example.com",
    "phone_number": "08012345678",
    "user_type": "artisan",
    "profile_picture_url": "https://res.cloudinary.com/workchop/profile_pictures/123e4567_a1b2c3d4.jpg",
    "bio": "Experienced plumber with 10 years experience"
  }
}
```

**Token Usage:**
- Include in subsequent requests as: `Authorization: Bearer {token}`
- Token expires in 7 days (configurable via ACCESS_TOKEN_EXPIRE_MINUTES)
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
  "detail": "Email address not verified. Please verify your email to continue."
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

#### Logout

**Endpoint:** `POST /auth/logout`

**Headers:**
- `Authorization`: Required, Bearer token

**Request Body:**
None (empty body)

**Success Response (200):**
```json
{
  "message": "Logged out successfully"
}
```

**Implementation Notes:**
- Blacklists the current JWT token in Redis
- Token will be invalid until it naturally expires
- User must login again to get a new token
- Token blacklist automatically expires after token lifetime

**Error Responses:**
- **401** - Unauthorized (invalid or missing token)

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
  "success": true,
  "message": "Password reset code sent to your email"
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
  "success": true,
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
  "success": true,
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

#### Change Password (Authenticated)

**Endpoint:** `POST /auth/change-password`

**Headers:**
- `Authorization`: Required, Bearer token

**Request Body:**
```json
{
  "current_password": "OldPassword123!",
  "new_password": "NewSecurePass123!",
  "confirm_password": "NewSecurePass123!"
}
```

**Field Requirements:**
- `current_password`: Required
- `new_password`: Required, minimum 8 characters
- `confirm_password`: Required, must match `new_password`

**Success Response (200):**
```json
{
  "success": true,
  "message": "Password changed successfully"
}
```

**Error Responses:**
- **400** - Current password incorrect, unchanged password, or validation failure
- **401** - Unauthorized

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
  "success": true,
  "message": "OTP sent successfully",
  "retry_after": 60
}
```

**Implementation Notes:**
- Always returns success message
- Invalidates previous OTPs
- Generates new 6-digit OTP
- OTP expires in 10 minutes
- `retry_after` indicates seconds to wait before requesting another OTP (default: 60)

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

1. **Token Storage:** Store the `token` from login response securely (e.g., HttpOnly cookies or secure storage)
2. **Token Expiry:** Token expires in 7 days (configurable). Implement refresh logic or re-login
3. **File Uploads:** Use `multipart/form-data` for profile picture upload
4. **OTP Expiry:** OTPs expire in 10 minutes. Show countdown timer
5. **Reset Token Expiry:** Reset tokens expire in 30 minutes
6. **Registration Flow:** All 5 steps must be completed in order
7. **User Types:** Only `"artisan"` and `"client"` are valid user types
8. **Response Format:** All successful responses include a `"success": true` field
9. **Services Selection:** Step 4 requires service names (strings), not IDs - fetch service names from GET /services endpoint first
10. **Email Verification:** Users must verify email before login. Unverified users will receive 403 error on login

---

## Services Module

### 1. Get All Services

**Endpoint:** `GET /services`

**Description:** Retrieve list of all available services that users can select during registration (Step 4).

**Query Parameters:**
- `skip`: Optional, integer (default: 0) - Number of records to skip for pagination
- `limit`: Optional, integer (default: 100) - Maximum number of records to return
- `category_id`: Optional, integer - Filter services by category ID

**Success Response (200):**
```json
[
  {
    "id": 14,
    "name": "Electrician",
    "description": "Professional electrical services including installation, wiring, repairs, and safety inspections",
    "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783311/electrician_asjxug.png",
    "category_id": null,
    "created_at": "2026-01-30T14:47:41Z",
    "category": null
  },
  {
    "id": 15,
    "name": "Plumbing",
    "description": "Expert plumbing solutions for pipe installations, leak repairs, and water system maintenance",
    "image": "https://res.cloudinary.com/dlw4um9gc/image/upload/v1769783357/plumber_xxipw0.png",
    "category_id": null,
    "created_at": "2026-01-30T14:47:41Z",
    "category": null
  }
]
```

**Available Services (12 total):**
1. **Electrician** - Professional electrical services
2. **Plumbing** - Expert plumbing solutions
3. **Carpentry** - Skilled woodworking services
4. **Cleaning** - Professional cleaning services
5. **Painting** - Quality painting services
6. **Beauty/Makeup** - Professional makeup artistry
7. **Construction** - Comprehensive construction services
8. **Auto Repair** - Complete auto repair services
9. **Electronics Repair** - Expert electronics repair
10. **Dry Cleaning** - Professional laundry services
11. **Fashion/Tailoring** - Custom tailoring services
12. **Home Repair** - General handyman services

**Implementation Notes:**
- All services include an `image` field with Cloudinary URL
- Services are sorted alphabetically by name
- Use exact service names (case-sensitive) when submitting in registration Step 4
- Currently, all services have `category_id: null` (categories optional)
- Frontend should fetch this list before Step 4 of registration

**IMPORTANT NOTE:**
Services are matched by **exact name** (case-sensitive), so the frontend MUST use the exact names returned from this endpoint when submitting in Step 4 registration. For example, use `"Electrician"` not `"electrician"` or `"Electrical"`.

**Error Responses:**
- **500** - Internal server error

---

### 2. Get Service Categories

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

### 3. Get Service Category with Services

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

### 4. Get Services (Deprecated - Use #1 Instead)

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

### 5. Get Service by ID

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

---

### Customer Profile Endpoints

Available to all authenticated users (both customers and artisans can access their basic profile).

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
  "profile_picture_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Looking for reliable artisans",
  "location_address": "6.52440, 3.37920",
  "location_latitude": 6.5244,
  "location_longitude": 3.3792,
  "is_email_verified": true,
  "is_active": true,
  "created_at": "2025-01-20T10:00:00Z"
}
```

**Field Descriptions:**
- `id`: User UUID (string)
- `full_name`: User's full name (string)
- `email`: User's email address (string)
- `phone_number`: User's phone number (string)
- `profile_picture_url`: Cloudinary image URL or null (string or null)
- `bio`: User biography (string or null)
- `location_address`: User location address/label (string or null)
- `location_latitude`: User latitude coordinate (number or null)
- `location_longitude`: User longitude coordinate (number or null)
- `is_email_verified`: Email verification status (boolean)
- `is_active`: Account active status (boolean)
- `created_at`: Account creation timestamp (ISO 8601 datetime string)

**Error Responses:**
- **401** - Unauthorized (invalid or missing token)

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
  "bio": "Updated bio text",
  "location": {
    "latitude": 6.5244,
    "longitude": 3.3792,
    "address": "Ikeja, Lagos"
  },
  "location_address": "Ikeja, Lagos"
}
```

**Field Requirements:**
- `full_name`: Optional, string (1-255 characters)
- `phone_number`: Optional, string (10-20 characters), must be unique
- `bio`: Optional, string (max 1000 characters)
- `location`: Optional object with:
  - `latitude`: Required if location provided, number (-90 to 90)
  - `longitude`: Required if location provided, number (-180 to 180)
  - `address`: Optional, string (max 500)
- `location_address`: Optional, string (max 500)

**Success Response (200):**
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "full_name": "Jane Smith Updated",
  "email": "jane@example.com",
  "phone_number": "08087654321",
  "profile_picture_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Updated bio text",
  "location_address": "Ikeja, Lagos",
  "location_latitude": 6.5244,
  "location_longitude": 3.3792,
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

#### Upload / Change Profile Picture

**Endpoint:** `PUT /profiles/me/profile-picture`

**Headers:**
- `Authorization`: Required, Bearer token
- `Content-Type`: `multipart/form-data`

**Form Data:**
- `profile_picture`: Required, image file (`jpg`, `jpeg`, `png`, `webp`, `gif`)

**Success Response (200):**
```json
{
  "message": "Profile picture updated successfully",
  "profile_picture_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/profile_pictures/123e4567_a1b2c3d4.jpg"
}
```

**Error Responses:**
- **400** - Invalid/unsupported image
- **401** - Unauthorized
- **500** - Failed to update profile picture

---

### Artisan Profile Endpoints

Only available to users with `user_type: "artisan"`.

#### Get My Artisan Profile (Private)

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
  "profile_picture_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Experienced plumber with 10 years",
  "user_type": "artisan",
  "location_address": "123 Main St, Lagos",
  "service_radius_km": 15.0,
  "hourly_rate_min": "5000.00",
  "hourly_rate_max": "15000.00",
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

**Field Descriptions:**
- `id`: User UUID (string)
- `full_name`: Artisan's full name (string)
- `email`: Artisan's email address (string) - **Private field**
- `phone_number`: Artisan's phone number (string) - **Private field**
- `profile_picture_url`: Cloudinary image URL or null (string or null)
- `bio`: Artisan biography (string or null)
- `user_type`: User type (string: "artisan")
- `location_address`: Human-readable address (string or null)
- `service_radius_km`: Service radius in kilometers (float, default: 10.0)
- `hourly_rate_min`: Minimum hourly rate in NGN (string decimal format like "5000.00" or null)
- `hourly_rate_max`: Maximum hourly rate in NGN (string decimal format like "15000.00" or null)
- `years_of_experience`: Years of experience (integer or null)
- `specialization`: Area of specialization (string or null)
- `is_verified`: Admin verification status (boolean)
- `verified_at`: Verification timestamp (ISO 8601 datetime string or null)
- `availability_status`: Current availability (string: "available", "busy", or "offline")
- `average_rating`: Average rating (float, 0.0 to 5.0)
- `total_ratings`: Number of ratings received (integer)
- `total_jobs_completed`: Total completed jobs (integer)
- `response_time_avg_minutes`: Average response time in minutes (integer or null)
- `acceptance_rate`: Job acceptance rate (float, 0.0 to 1.0) - **Private field**
- `created_at`: Account creation timestamp (ISO 8601 datetime string)

**Implementation Notes:**
- If artisan profile doesn't exist, it will be created automatically with default values
- Returns private view with all details including email, phone_number, and acceptance_rate
- `service_radius_km` defaults to 10.0 if not set

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
- `full_name`: Optional, string (1-255 characters)
- `phone_number`: Optional, string (10-20 characters), must be unique
- `bio`: Optional, string (max 1000 characters)
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
Returns full artisan profile (same format as GET /profiles/artisans/me):
```json
{
  "id": "123e4567-e89b-12d3-a456-426614174000",
  "full_name": "John Doe",
  "email": "john@example.com",
  "phone_number": "08012345678",
  "profile_picture_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Experienced plumber with 10 years",
  "user_type": "artisan",
  "location_address": "123 Main St, Lagos",
  "service_radius_km": 15.0,
  "hourly_rate_min": "5000.00",
  "hourly_rate_max": "15000.00",
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
- **400** - Phone number already registered
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
Returns full artisan profile (same format as GET /profiles/artisans/me)

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

**Field Descriptions:**
- `average_rating`: Average rating (float, 0.0 to 5.0)
- `total_ratings`: Number of ratings received (integer)
- `total_jobs_completed`: Total completed jobs (integer)
- `response_time_avg_minutes`: Average response time in minutes (integer or null)
- `acceptance_rate`: Job acceptance rate (float, 0.0 to 1.0)

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
  "profile_picture_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/profile_pictures/123e4567_a1b2c3d4.jpg",
  "bio": "Experienced plumber with 10 years",
  "location_address": "123 Main St, Lagos",
  "service_radius_km": 15.0,
  "hourly_rate_min": "5000.00",
  "hourly_rate_max": "15000.00",
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

**Field Descriptions:**
- All fields same as private profile, except:
- **NO** `email` (private)
- **NO** `phone_number` (private)
- **NO** `user_type` (not needed)
- **NO** `acceptance_rate` (private)
- **NO** `verified_at` (not needed)
- **NO** `created_at` (not needed)

**Implementation Notes:**
- Returns public view only - excludes email, phone number, acceptance_rate, and other sensitive/private details
- Used when customers view artisan profiles during search

**Error Responses:**
- **400** - User is not an artisan
- **404** - Artisan not found
- **500** - Failed to fetch profile

---

### Portfolio Management (Artisan Only)

All portfolio endpoints are only available to artisans.

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
    "image_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/portfolio/image1.jpg",
    "title": "Bathroom Renovation",
    "description": "Complete bathroom renovation for residential client",
    "project_date": "2025-01-15T00:00:00Z",
    "display_order": 1,
    "created_at": "2025-01-16T10:00:00Z"
  },
  {
    "id": 2,
    "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
    "image_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/portfolio/image2.jpg",
    "title": "Kitchen Plumbing",
    "description": "Installed new kitchen sink and fixtures",
    "project_date": null,
    "display_order": 2,
    "created_at": "2025-01-17T10:00:00Z"
  }
]
```

**Field Descriptions:**
- `id`: Portfolio item ID (integer)
- `artisan_id`: Artisan's user UUID (string)
- `image_url`: Cloudinary image URL (string, required)
- `title`: Portfolio item title (string or null)
- `description`: Portfolio item description (string or null)
- `project_date`: Project completion date (ISO 8601 datetime string or null)
- `display_order`: Display order for sorting (integer, default: 0)
- `created_at`: Creation timestamp (ISO 8601 datetime string)

**Implementation Notes:**
- Returns empty array `[]` if no portfolio items
- Sorted by display_order (ascending), then created_at (descending/newest first)

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
- Image is compressed and optimized for web delivery

**Success Response (201):**
```json
{
  "id": 1,
  "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
  "image_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/portfolio/image1.jpg",
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
- This endpoint updates metadata only, **not the image**
- To change the image, delete and create a new portfolio item
- All fields are optional - only send fields you want to update

**Success Response (200):**
```json
{
  "id": 1,
  "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
  "image_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/portfolio/image1.jpg",
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
- Deletes both the database record and the image from Cloudinary
- Returns 204 No Content on success
- This action is irreversible

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
    "image_url": "https://res.cloudinary.com/workchop/image/upload/v1234567890/portfolio/image1.jpg",
    "title": "Bathroom Renovation",
    "description": "Complete bathroom renovation for residential client",
    "project_date": "2025-01-15T00:00:00Z",
    "display_order": 1,
    "created_at": "2025-01-16T10:00:00Z"
  }
]
```

**Implementation Notes:**
- Returns empty array `[]` if artisan has no portfolio items
- Sorted by display_order (ascending), then created_at (descending/newest first)
- Same response format as private endpoint

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
category_id (optional): int - Filter by service category (currently services have no categories assigned)
service_ids (optional): string - Comma-separated service IDs (e.g., "14,15,16")
min_hourly_rate (optional): decimal, >= 0
max_hourly_rate (optional): decimal, >= 0
min_rating (optional): float, 0 to 5
verified_only (optional): boolean, default: false
availability_status (optional): string - One of: "available", "busy", "offline"
min_years_experience (optional): int, >= 0
sort_by (optional): string - One of: "distance", "rating", "price", "experience", "jobs_completed", "response_time", default: "distance"
sort_order (optional): string - One of: "asc", "desc", default: "asc"
page (optional): int, >= 1, default: 1
page_size (optional): int, 1 to 100, default: 20
```

**Example Request:**
```
GET /search/artisans?latitude=6.5244&longitude=3.3792&radius_km=15&service_ids=14,15&verified_only=true&min_rating=4.0&sort_by=rating&sort_order=desc&page=1&page_size=10
```

**Success Response (200):**
```json
{
  "results": [
    {
      "id": "0b4467de-2616-4c9f-bf0a-d4db849e26c9",
      "full_name": "John Electrician",
      "profile_picture": null,
      "location_address": "Lagos, Nigeria",
      "service_radius_km": 25.0,
      "hourly_rate_min": "5000.00",
      "hourly_rate_max": "10000.00",
      "years_of_experience": 8,
      "specialization": "Residential & Commercial Electrical Work",
      "is_verified": true,
      "availability_status": "available",
      "average_rating": 3.8,
      "total_ratings": 26,
      "total_jobs_completed": 94,
      "response_time_avg_minutes": 81,
      "acceptance_rate": 0.84,
      "distance_km": 2.47,
      "services": ["Electrician"],
      "portfolio_sample": null
    }
  ],
  "total": 10,
  "page": 1,
  "page_size": 10,
  "total_pages": 1,
  "search_location": {
    "latitude": 6.5244,
    "longitude": 3.3792
  },
  "filters_applied": {
    "radius_km": 15.0,
    "verified_only": true,
    "service_ids": [14, 15],
    "min_rating": 4.0
  }
}
```

**Response Fields:**
- `results`: Array of artisan search results
  - `id`: Artisan user ID (UUID string)
  - `full_name`: Artisan's full name (string)
  - `profile_picture`: URL to profile image or null
  - `location_address`: Human-readable address (string or null)
  - `service_radius_km`: How far the artisan is willing to travel (float)
  - `hourly_rate_min`: Minimum hourly rate in NGN (string in decimal format like "5000.00" or null)
  - `hourly_rate_max`: Maximum hourly rate in NGN (string in decimal format like "10000.00" or null)
  - `years_of_experience`: Years of experience (integer or null)
  - `specialization`: Artisan's area of specialization (string or null)
  - `is_verified`: Whether artisan is verified (boolean)
  - `availability_status`: Current availability (string: "available", "busy", or "offline")
  - `average_rating`: Average rating (float, 0.0 to 5.0)
  - `total_ratings`: Number of ratings received (integer)
  - `total_jobs_completed`: Total completed jobs (integer)
  - `response_time_avg_minutes`: Average response time in minutes (integer or null)
  - `acceptance_rate`: Job acceptance rate (float, 0.0 to 1.0)
  - `distance_km`: Distance from search location in kilometers (float, rounded to 2 decimals)
  - `services`: Array of service names offered by artisan (array of strings)
  - `portfolio_sample`: URL to one portfolio image or null
- `total`: Total number of results matching criteria (integer)
- `page`: Current page number (integer)
- `page_size`: Number of results per page (integer)
- `total_pages`: Total number of pages (integer)
- `search_location`: The coordinates used for search (object with latitude and longitude)
- `filters_applied`: Summary of filters used in the search (object with applied filter keys and values)

**Implementation Notes:**
- Uses PostGIS ST_DWithin for efficient spatial queries
- Distance is calculated using ST_Distance and returned in kilometers
- Results are distinct (no duplicate artisans even if they offer multiple services)
- If service_ids or category_id filters are used, only artisans offering those services are returned
- Price filtering considers both min and max hourly rates (shows artisan if rate range overlaps filter)
- Sorting by "price" uses hourly_rate_min
- Pagination starts at page 1
- **Data Types:** Decimal fields (hourly rates) are returned as strings (e.g., "5000.00") not numbers
- The `service_ids` parameter accepts a comma-separated string of IDs (e.g., "14,15"), which is parsed and returned as an array in filters_applied

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

**IMPORTANT LIMITATION:** This endpoint currently requires services to have a category assigned. Since all services in the current database have `category_id = null`, this endpoint will return an empty array `[]` until service categories are properly configured.

**Query Parameters:**
```
latitude (required): float, -90 to 90
longitude (required): float, -180 to 180
radius_km (optional): float, 0.1 to 100, default: 10.0
category_id (optional): int
```

**Example Request:**
```
GET /search/services/availability?latitude=6.5244&longitude=3.3792&radius_km=20
```

**Success Response (200):**
```json
[]
```

**Note:** Currently returns empty array because services don't have categories assigned. Once categories are configured, the response format will be:
```json
[
  {
    "service_id": 1,
    "service_name": "Pipe Installation",
    "category_id": 1,
    "category_name": "Plumbing",
    "artisans_available": 12,
    "average_hourly_rate": "8500.50",
    "average_rating": 4.3,
    "closest_artisan_distance_km": 1.25
  }
]
```

**Response Fields (when categories are configured):**
- `service_id`: Service ID (integer)
- `service_name`: Name of the service (string)
- `category_id`: Category ID (integer)
- `category_name`: Category name (string)
- `artisans_available`: Number of available artisans offering this service (integer)
- `average_hourly_rate`: Average hourly rate for this service (string in decimal format like "8500.50" or null)
- `average_rating`: Average rating of artisans offering this service (float or null, rounded to 1 decimal)
- `closest_artisan_distance_km`: Distance to the closest artisan offering this service (float or null, rounded to 2 decimals)

**Implementation Notes:**
- Only counts artisans with availability_status = "available"
- Requires services to have category_id assigned (INNER JOIN with service_categories table)
- Results are grouped by service and ordered by category name, then service name
- Statistics are calculated only for artisans within the specified radius
- If no artisans are available for a service, it won't appear in results
- **Currently non-functional** due to missing service categories in database

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
GET /search/artisans/nearby/summary?latitude=6.5244&longitude=3.3792&radius_km=50
```

**Success Response (200):**
```json
{
  "total_artisans": 10,
  "total_verified": 5,
  "total_available": 10,
  "services_offered": 10,
  "average_rating": 4.4,
  "distance_range_km": {
    "min": 2.47,
    "max": 4.56
  }
}
```

**Response Fields:**
- `total_artisans`: Total number of artisans in the area (integer)
- `total_verified`: Number of verified artisans (integer)
- `total_available`: Number of currently available artisans (integer, where availability_status = "available")
- `services_offered`: Total number of unique services offered by all artisans in the area (integer)
- `average_rating`: Average rating across all artisans (float, rounded to 1 decimal, defaults to 0.0 if no artisans)
- `distance_range_km`: Distance range of artisans found (object)
  - `min`: Distance to the closest artisan (float, rounded to 2 decimals, defaults to 0.0 if no artisans)
  - `max`: Distance to the farthest artisan within radius (float, rounded to 2 decimals, defaults to 0.0 if no artisans)

**Implementation Notes:**
- Useful for showing availability indicators before performing detailed search
- Can be used to determine if it's worth expanding search radius
- All statistics exclude inactive users (is_active = false)
- Average rating is calculated across all artisans, not weighted by number of ratings
- Only counts artisans with location data set (location IS NOT NULL)
- Services count includes all unique services offered by artisans in the area

**Error Responses:**
- **400** - Invalid query parameters
- **500** - Database or server error

---

## Wallet Module

### Overview
The wallet module allows artisans to track their earnings, view payment history, and manage payouts. All wallet endpoints are artisan-only.

### 1. Get Wallet Balance

**Endpoint:** `GET /wallet/balance`

**Authentication:** Required (Artisan only)

**Success Response (200):**
```json
{
  "total_earned": "125000.00",
  "pending_release": "25000.00",
  "total_jobs_completed": 15,
  "total_jobs_paid": 12,
  "lifetime_earnings": "125000.00"
}
```

**Field Descriptions:**
- `total_earned`: Total amount released to artisan (withdrawn/paid out)
- `pending_release`: Payments that are SUCCESS (paid by customer) but not yet released to artisan
- `total_jobs_completed`: Count of completed bookings
- `total_jobs_paid`: Count of paid bookings (PAID, IN_PROGRESS, or COMPLETED status)
- `lifetime_earnings`: All-time earnings (currently same as total_earned)

**Error Responses:**
- **403** - Only artisans can access wallet

**Notes:**
- Shows real-time balance calculated from payment records
- Pending release represents funds held in escrow awaiting job completion
- Total earned only includes RELEASED payments (actual payouts)

---

### 2. Get Earnings History

**Endpoint:** `GET /wallet/earnings`

**Authentication:** Required (Artisan only)

**Query Parameters:**
- `status_filter` (optional): Filter by payment status (pending, success, released, etc.)
- `page` (optional, default 1): Page number
- `page_size` (optional, default 20, max 100): Items per page

**Success Response (200):**
```json
{
  "earnings": [
    {
      "payment_id": 1,
      "payment_reference": "PAY-2026-000001",
      "booking_id": 1,
      "booking_reference": "BK-2026-000001",
      "amount": "7500.00",
      "status": "success",
      "customer_name": "Alice Customer",
      "service_name": "Electrician",
      "job_date": "2026-02-15T10:00:00Z",
      "paid_at": "2026-02-05T14:15:00Z",
      "released_at": null,
      "created_at": "2026-02-05T14:10:00Z"
    }
  ],
  "total": 25,
  "page": 1,
  "page_size": 20,
  "summary": {
    "total_amount": "187500.00",
    "count": 20
  }
}
```

**Error Responses:**
- **400** - Invalid status filter
- **403** - Only artisans can access earnings history

**Notes:**
- Shows all payments related to artisan's bookings
- Includes booking and customer details for context
- Summary shows totals for the current page
- Can filter by status to see only released payments, pending, etc.

---

### 3. Get Payout History

**Endpoint:** `GET /wallet/payouts`

**Authentication:** Required (Artisan only)

**Query Parameters:**
- `page` (optional, default 1): Page number
- `page_size` (optional, default 20, max 100): Items per page

**Success Response (200):**
```json
{
  "payouts": [
    {
      "payment_id": 1,
      "payment_reference": "PAY-2026-000001",
      "payout_reference": "PAYOUT-PAY-2026-000001",
      "amount": "7500.00",
      "released_at": "2026-02-15T15:00:00Z",
      "booking_reference": "BK-2026-000001",
      "customer_name": "Alice Customer"
    }
  ],
  "total": 10,
  "page": 1,
  "page_size": 20
}
```

**Error Responses:**
- **403** - Only artisans can access payout history

**Notes:**
- Shows only RELEASED payments (actual payouts received)
- Ordered by release date (most recent first)
- Includes payout reference for tracking
- This represents money that has actually been paid out to the artisan

---

### 4. Get Wallet Statistics

**Endpoint:** `GET /wallet/stats`

**Authentication:** Required (Artisan only)

**Success Response (200):**
```json
{
  "total_earnings": "125000.00",
  "average_job_value": "8333.33",
  "highest_earning": "25000.00",
  "lowest_earning": "5000.00",
  "total_transactions": 15
}
```

**Field Descriptions:**
- `total_earnings`: Sum of all successful payments
- `average_job_value`: Mean payment amount
- `highest_earning`: Maximum single payment
- `lowest_earning`: Minimum single payment
- `total_transactions`: Count of successful payments

**Error Responses:**
- **403** - Only artisans can access wallet stats

**Notes:**
- Useful for analytics and performance tracking
- Only includes SUCCESS and RELEASED payments
- Excludes pending, failed, and refunded payments

---

### 5. Get Supported Banks

**Endpoint:** `GET /wallet/banks`

**Authentication:** Required (Artisan only)

**Success Response (200):**
```json
[
  {
    "name": "Access Bank",
    "code": "044",
    "slug": "access-bank"
  },
  {
    "name": "Zenith Bank",
    "code": "057",
    "slug": "zenith-bank"
  }
]
```

**Error Responses:**
- **403** - Only artisans can access wallet
- **500** - Failed to fetch banks from Paystack

**Notes:**
- Returns Paystack-supported banks, sorted alphabetically by name
- Use this endpoint to populate bank dropdowns

---

### 6. Verify Bank Account

**Endpoint:** `POST /wallet/account/verify`

**Authentication:** Required (Artisan only)

**Request Body:**
```json
{
  "account_number": "0123456789",
  "bank_code": "057"
}
```

**Success Response (200):**
```json
{
  "account_number": "0123456789",
  "account_name": "JOHN ARTISAN",
  "bank_code": "057",
  "bank_name": "Zenith Bank",
  "verified": true
}
```

**Error Responses:**
- **400** - Account verification failed
- **403** - Only artisans can access wallet

**Notes:**
- Use this before payout submission to auto-fill/confirm account name
- Verification is done against Paystack `bank/resolve`

---

### 7. Request Payout

**Endpoint:** `POST /wallet/payout/request`

**Authentication:** Required (Artisan only)

**Request Body:**
```json
{
  "amount": 50000.00,
  "account_number": "0123456789",
  "bank_code": "057",
  "account_name": "John Artisan"
}
```

**Field Requirements:**
- `amount`: Required, decimal, minimum ₦5,000, must not exceed available balance
- `account_number`: Required, string, 10-digit bank account number
- `bank_code`: Required, string, Nigerian bank code (e.g., "057" for Zenith)
- `account_name`: Required, string, account holder's name

**Success Response (200):**
```json
{
  "success": true,
  "message": "Payout of ₦50000.00 initiated successfully",
  "payout_reference": "BATCH-20260205141530",
  "amount": "50000.00",
  "account_number": "0123456789",
  "bank_code": "057",
  "status": "processing"
}
```

**Error Responses:**
- **400** - Below minimum amount, insufficient balance, or invalid bank details
- **403** - Only artisans can request payouts
- **500** - Paystack API error (bank verification failed, transfer failed, etc.)

**Notes:**
- Minimum payout amount: ₦5,000
- Available balance = Pending Release (SUCCESS status payments)
- Bank account is verified with Paystack before processing
- Multiple payments may be released to fulfill the requested amount
- Payments are released in chronological order (oldest first)
- Once released, payment status changes to RELEASED

**Common Bank Codes:**
- Access Bank: 044
- GTBank: 058
- First Bank: 011
- UBA: 033
- Zenith Bank: 057
- [Full list available via Paystack API]

---

## Additional Notes for Frontend Implementation

### Profile & Portfolio Module

1. **Authentication:** Profile and portfolio endpoints require JWT Bearer token (search endpoints are public)
2. **User Types:** Customer profile endpoints are available to all users; artisan profile endpoints only to artisans
3. **Public vs Private Profiles:** Artisan public profiles exclude: email, phone_number, acceptance_rate, verified_at, created_at, and user_type
4. **Image URLs:** Profile and portfolio images are hosted on Cloudinary with URLs like `https://res.cloudinary.com/workchop/image/upload/...` (can also be `null`)
5. **Availability Status:** Valid values are `"available"`, `"busy"`, `"offline"`
6. **Location:** When updating artisan location, both latitude and longitude are required together
7. **Portfolio Images:** Portfolio images support larger file sizes (10MB vs 5MB for profiles)
8. **Image Dimensions:** Portfolio images are resized to max 1920x1920, profiles to 1080x1080
9. **Decimal Values:** Hourly rates (hourly_rate_min, hourly_rate_max) are returned as strings in JSON (e.g., "5000.00" not 5000). Parse them as numbers in your frontend code.
10. **Service Radius Default:** The `service_radius_km` field defaults to 10.0 if not set by the artisan

### Search Module

11. **Search Radius:** Default search radius is 10km, maximum is 100km
12. **Coordinates:** Nigeria's approximate coordinates: Lagos (6.5244, 3.3792), Abuja (9.0765, 7.3986), Port Harcourt (4.8156, 7.0498)
13. **Distance Calculation:** All distances use PostGIS ST_Distance on WGS84 geography for accurate results
14. **Search Performance:** Location-based searches are optimized with spatial indexes for fast queries
15. **Decimal Values in Search:** All decimal/money fields (hourly rates, average rates) are returned as strings in JSON (e.g., "5000.00" not 5000.00). Parse them as numbers in your frontend code.
16. **Service IDs Filter:** When using `service_ids` parameter, pass as comma-separated string (e.g., "14,15,16"), not as an array
17. **Service Categories:** The `/search/services/availability` endpoint is currently non-functional because services don't have categories assigned. It will return an empty array until service categories are configured in the database.

---

## Booking Module

### Overview
The booking system allows customers to book artisan services, make payments via Paystack, track job progress, and leave reviews. The flow follows these status transitions:

**Status Flow:**
```
PENDING → ACCEPTED → PAID → IN_PROGRESS → COMPLETED
   ↓         ↓
REJECTED  CANCELLED
```

### 1. Create Booking

**Endpoint:** `POST /bookings`

**Authentication:** Required (Customer only)

**Request Body:**
```json
{
  "artisan_id": "123e4567-e89b-12d3-a456-426614174000",
  "service_id": 14,
  "job_description": "Need electrical wiring for new room",
  "job_date": "2026-02-15T10:00:00Z",
  "job_address": "123 Main Street, Lagos, Nigeria",
  "job_latitude": 6.5244,
  "job_longitude": 3.3792,
  "budget_min": 5000.00,
  "budget_max": 10000.00
}
```

**Field Requirements:**
- `artisan_id`: Required, UUID of the artisan
- `service_id`: Required, integer ID of the service
- `job_description`: Optional, text description
- `job_date`: Required, ISO 8601 datetime, must be in the future
- `job_address`: Required, string (5-500 characters)
- `job_latitude`: Required, float (-90 to 90)
- `job_longitude`: Required, float (-180 to 180)
- `budget_min`: Required, decimal (>= 0)
- `budget_max`: Required, decimal (>= budget_min)

**Success Response (201):**
```json
{
  "id": 1,
  "booking_reference": "BK-2026-000001",
  "customer_id": "customer-uuid",
  "artisan_id": "artisan-uuid",
  "service_id": 14,
  "job_description": "Need electrical wiring for new room",
  "job_date": "2026-02-15T10:00:00Z",
  "job_address": "123 Main Street, Lagos, Nigeria",
  "job_latitude": 6.5244,
  "job_longitude": 3.3792,
  "budget_min": "5000.00",
  "budget_max": "10000.00",
  "agreed_amount": null,
  "status": "pending",
  "accepted_at": null,
  "paid_at": null,
  "started_at": null,
  "completed_at": null,
  "cancelled_at": null,
  "completion_notes": null,
  "completion_images": null,
  "cancellation_reason": null,
  "rejection_reason": null,
  "created_at": "2026-02-05T14:00:00Z",
  "updated_at": "2026-02-05T14:00:00Z"
}
```

**Error Responses:**
- **400** - Validation error (invalid date, budget range, coordinates)
- **403** - Only customers can create bookings
- **404** - Artisan or service not found

---

### 2. List Bookings

**Endpoint:** `GET /bookings`

**Authentication:** Required

**Query Parameters:**
- `status` (optional): Filter by status (pending, accepted, paid, in_progress, completed, cancelled, rejected, disputed)
- `page` (optional, default 1): Page number
- `page_size` (optional, default 20, max 100): Items per page

**Success Response (200):**
```json
{
  "bookings": [
    {
      "id": 1,
      "booking_reference": "BK-2026-000001",
      "status": "pending",
      ...
    }
  ],
  "total": 5,
  "page": 1,
  "page_size": 20
}
```

**Notes:**
- Customers see bookings they created
- Artisans see bookings assigned to them

---

### 3. Get Single Booking

**Endpoint:** `GET /bookings/{booking_id}`

**Authentication:** Required

**Success Response (200):**
```json
{
  "id": 1,
  "booking_reference": "BK-2026-000001",
  "customer_id": "customer-uuid",
  "artisan_id": "artisan-uuid",
  ...
}
```

**Error Responses:**
- **403** - User doesn't have permission to view this booking
- **404** - Booking not found

---

### 4. Get Booking Statistics

**Endpoint:** `GET /bookings/stats`

**Authentication:** Required

**Success Response (200):**
```json
{
  "total_bookings": 10,
  "pending_bookings": 2,
  "accepted_bookings": 1,
  "paid_bookings": 3,
  "in_progress_bookings": 1,
  "completed_bookings": 2,
  "cancelled_bookings": 1,
  "rejected_bookings": 0,
  "disputed_bookings": 0
}
```

---

### 5. Accept Booking (Artisan)

**Endpoint:** `PATCH /bookings/{booking_id}/accept`

**Authentication:** Required (Artisan only)

**Request Body:**
```json
{
  "agreed_amount": 7500.00
}
```

**Field Requirements:**
- `agreed_amount`: Required, decimal, must be within budget range (budget_min <= agreed_amount <= budget_max)

**Success Response (200):**
```json
{
  "id": 1,
  "booking_reference": "BK-2026-000001",
  "agreed_amount": "7500.00",
  "status": "accepted",
  "accepted_at": "2026-02-05T14:05:00Z",
  ...
}
```

**Error Responses:**
- **400** - Agreed amount outside budget range, or booking not in PENDING status
- **403** - Only assigned artisan can accept
- **404** - Booking not found

---

### 6. Reject Booking (Artisan)

**Endpoint:** `PATCH /bookings/{booking_id}/reject`

**Authentication:** Required (Artisan only)

**Request Body:**
```json
{
  "rejection_reason": "Schedule conflict, not available on this date"
}
```

**Field Requirements:**
- `rejection_reason`: Required, string (10-500 characters)

**Success Response (200):**
```json
{
  "id": 1,
  "booking_reference": "BK-2026-000001",
  "status": "rejected",
  "rejection_reason": "Schedule conflict, not available on this date",
  ...
}
```

**Error Responses:**
- **400** - Booking not in PENDING status
- **403** - Only assigned artisan can reject
- **404** - Booking not found

---

### 7. Start Booking (Artisan)

**Endpoint:** `PATCH /bookings/{booking_id}/start`

**Authentication:** Required (Artisan only)

**Request Body:** None

**Success Response (200):**
```json
{
  "id": 1,
  "booking_reference": "BK-2026-000001",
  "status": "in_progress",
  "started_at": "2026-02-15T10:15:00Z",
  ...
}
```

**Error Responses:**
- **400** - Booking not in PAID status
- **403** - Only assigned artisan can start
- **404** - Booking not found

---

### 8. Complete Booking (Artisan)

**Endpoint:** `PATCH /bookings/{booking_id}/complete`

**Authentication:** Required (Artisan only)

**Request Body:**
```json
{
  "completion_notes": "Fixed the electrical wiring and tested all outlets",
  "completion_images": [
    "https://res.cloudinary.com/workchop/image/upload/v1234/job1.jpg",
    "https://res.cloudinary.com/workchop/image/upload/v1234/job2.jpg"
  ]
}
```

**Field Requirements:**
- `completion_notes`: Optional, string (max 1000 characters)
- `completion_images`: Optional, array of image URLs (max 10 images)

**Success Response (200):**
```json
{
  "id": 1,
  "booking_reference": "BK-2026-000001",
  "status": "completed",
  "completed_at": "2026-02-15T14:30:00Z",
  "completion_notes": "Fixed the electrical wiring and tested all outlets",
  "completion_images": [
    "https://res.cloudinary.com/workchop/image/upload/v1234/job1.jpg",
    "https://res.cloudinary.com/workchop/image/upload/v1234/job2.jpg"
  ],
  ...
}
```

**Error Responses:**
- **400** - Booking not in IN_PROGRESS status
- **403** - Only assigned artisan can complete
- **404** - Booking not found

---

### 9. Cancel Booking (Customer)

**Endpoint:** `PATCH /bookings/{booking_id}/cancel`

**Authentication:** Required (Customer only)

**Request Body:**
```json
{
  "cancellation_reason": "Changed my mind, will book later"
}
```

**Field Requirements:**
- `cancellation_reason`: Required, string (10-500 characters)

**Success Response (200):**
```json
{
  "id": 1,
  "booking_reference": "BK-2026-000001",
  "status": "cancelled",
  "cancelled_at": "2026-02-05T14:10:00Z",
  "cancellation_reason": "Changed my mind, will book later",
  ...
}
```

**Error Responses:**
- **400** - Can only cancel bookings in PENDING or ACCEPTED status (before payment)
- **403** - Only booking owner can cancel
- **404** - Booking not found

**Notes:**
- Bookings can only be cancelled before payment
- For paid bookings, contact support for cancellation and refund

---

## Payment Module

### Overview
Payments are processed via Paystack payment gateway. The system implements a hold-and-release model where funds are held by Paystack until the job is completed, then released to the artisan.

**Paystack Test Cards:**
- Success: `4084084084084081`
- Decline: `4084084084084085`

### 1. Initialize Payment

**Endpoint:** `POST /payments/initialize`

**Authentication:** Required (Customer only)

**Request Body:**
```json
{
  "booking_id": 1
}
```

**Field Requirements:**
- `booking_id`: Required, integer, booking must be in ACCEPTED status

**Success Response (201):**
```json
{
  "id": 1,
  "payment_reference": "PAY-2026-000001",
  "booking_id": 1,
  "authorization_url": "https://checkout.paystack.com/bl99r9sm6q7dndg",
  "amount": "7500.00",
  "status": "pending",
  "created_at": "2026-02-05T14:10:00Z"
}
```

**Error Responses:**
- **400** - Booking not in ACCEPTED status, or payment already exists
- **403** - Only customer who owns the booking can initialize payment
- **404** - Booking not found
- **500** - Paystack API error

**Notes:**
- Redirect user to `authorization_url` to complete payment
- After payment, Paystack will send a webhook to update the booking status
- Customer will be redirected back to your app (configure callback URL in Paystack dashboard)

---

### 2. Verify Payment

**Endpoint:** `GET /payments/verify/{payment_reference}`

**Authentication:** Required

**Success Response (200):**
```json
{
  "payment_reference": "PAY-2026-000001",
  "status": "success",
  "amount": "7500.00",
  "paid": true,
  "message": "Payment verified successfully"
}
```

**Error Responses:**
- **403** - User doesn't have permission to verify this payment
- **404** - Payment not found
- **500** - Paystack verification error

**Notes:**
- Call this endpoint after user returns from Paystack to confirm payment status
- If `paid: true`, booking status will be updated to PAID

---

### 3. Get Payment Details

**Endpoint:** `GET /payments/{payment_id}`

**Authentication:** Required

**Success Response (200):**
```json
{
  "id": 1,
  "payment_reference": "PAY-2026-000001",
  "paystack_reference": "T1234567890",
  "booking_id": 1,
  "authorization_url": "https://checkout.paystack.com/bl99r9sm6q7dndg",
  "amount": "7500.00",
  "currency": "NGN",
  "payment_method": "card",
  "status": "success",
  "customer_email": "customer@example.com",
  "customer_name": "Alice Customer",
  "paid_at": "2026-02-05T14:15:00Z",
  "released_at": null,
  "refunded_at": null,
  "failed_at": null,
  "payout_reference": null,
  "created_at": "2026-02-05T14:10:00Z",
  "updated_at": "2026-02-05T14:15:00Z"
}
```

**Error Responses:**
- **403** - User doesn't have permission to view this payment
- **404** - Payment not found

---

### 4. Paystack Webhook

**Endpoint:** `POST /payments/webhook`

**Authentication:** None (signature verification)

**Headers:**
- `x-paystack-signature`: Webhook signature for verification

**Request Body (Paystack sends):**
```json
{
  "event": "charge.success",
  "data": {
    "reference": "PAY-2026-000001",
    "amount": 750000,
    "status": "success",
    "customer": {
      "email": "customer@example.com"
    },
    "channel": "card"
  }
}
```

**Success Response (200):**
```json
{
  "status": "success",
  "message": "Payment processed"
}
```

**Notes:**
- This endpoint is called by Paystack, not your frontend
- Configure webhook URL in Paystack dashboard: `https://yourdomain.com/api/v1/payments/webhook`
- Webhook signature is verified for security
- Automatically updates booking status to PAID when payment succeeds

---

### 5. Release Payment to Artisan

**Endpoint:** `POST /payments/{payment_id}/release`

**Authentication:** Required (Admin or Artisan)

**Request Body (optional):**
```json
{
  "account_number": "0123456789",
  "bank_code": "057",
  "account_name": "John Artisan"
}
```

**Success Response (200):**
```json
{
  "id": 1,
  "payment_reference": "PAY-2026-000001",
  "status": "released",
  "released_at": "2026-02-15T15:00:00Z",
  "payout_reference": "PAYOUT-PAY-2026-000001",
  ...
}
```

**Error Responses:**
- **400** - Payment not in SUCCESS status, or booking not COMPLETED
- **403** - Only assigned artisan can release payment
- **404** - Payment not found
- **500** - Paystack transfer error

**Notes:**
- Payment can only be released after job is completed
- Funds are transferred from Paystack balance to artisan's bank account
- In production, this should be admin-only or auto-triggered after review period

---

## Review Module

### Overview
Customers can review artisans after job completion. Reviews automatically update artisan statistics (average rating, total reviews, jobs completed).

### 1. Create Review

**Endpoint:** `POST /reviews`

**Authentication:** Required (Customer only)

**Request Body:**
```json
{
  "booking_id": 1,
  "rating": 4.5,
  "review_text": "Excellent service! Very professional and fixed the issue quickly.",
  "is_anonymous": false
}
```

**Field Requirements:**
- `booking_id`: Required, integer, booking must be COMPLETED
- `rating`: Required, float (1.0-5.0), in 0.5 increments (1.0, 1.5, 2.0, etc.)
- `review_text`: Optional, string (max 1000 characters)
- `is_anonymous`: Optional, boolean (default false)

**Success Response (201):**
```json
{
  "id": 1,
  "booking_id": 1,
  "customer_id": "customer-uuid",
  "artisan_id": "artisan-uuid",
  "rating": 4.5,
  "review_text": "Excellent service! Very professional and fixed the issue quickly.",
  "is_anonymous": false,
  "is_flagged": false,
  "artisan_response": null,
  "artisan_responded_at": null,
  "customer_name": "Alice Customer",
  "artisan_name": "John Electrician",
  "created_at": "2026-02-15T15:30:00Z",
  "updated_at": "2026-02-15T15:30:00Z"
}
```

**Error Responses:**
- **400** - Booking not completed, or review already exists
- **403** - Only customer who owns the booking can review
- **404** - Booking not found

**Notes:**
- Only one review per booking
- Rating must be in 0.5 increments (validated)
- Automatically updates artisan's average_rating and total_ratings in artisan_profile

---

### 2. Get Artisan Reviews

**Endpoint:** `GET /reviews/artisan/{artisan_id}`

**Authentication:** Not required (public)

**Query Parameters:**
- `page` (optional, default 1): Page number
- `page_size` (optional, default 20, max 100): Items per page

**Success Response (200):**
```json
{
  "reviews": [
    {
      "id": 1,
      "booking_id": 1,
      "customer_id": "customer-uuid",
      "artisan_id": "artisan-uuid",
      "rating": 4.5,
      "review_text": "Excellent service!",
      "is_anonymous": false,
      "is_flagged": false,
      "artisan_response": "Thank you for the kind words!",
      "artisan_responded_at": "2026-02-15T16:00:00Z",
      "customer_name": "Alice Customer",
      "artisan_name": "John Electrician",
      "created_at": "2026-02-15T15:30:00Z",
      "updated_at": "2026-02-15T16:00:00Z"
    }
  ],
  "total": 25,
  "average_rating": 4.3,
  "rating_distribution": {
    "1": 0,
    "2": 1,
    "3": 3,
    "4": 8,
    "5": 13
  }
}
```

**Error Responses:**
- **404** - Artisan not found

**Notes:**
- Public endpoint, no authentication required
- Anonymous reviews hide customer_name (returns null)
- Excludes flagged reviews

---

### 3. Get Review for Booking

**Endpoint:** `GET /reviews/booking/{booking_id}`

**Authentication:** Required

**Success Response (200):**
```json
{
  "id": 1,
  "booking_id": 1,
  "customer_id": "customer-uuid",
  "artisan_id": "artisan-uuid",
  "rating": 4.5,
  "review_text": "Excellent service!",
  "is_anonymous": false,
  "is_flagged": false,
  "artisan_response": "Thank you!",
  "artisan_responded_at": "2026-02-15T16:00:00Z",
  "customer_name": "Alice Customer",
  "artisan_name": "John Electrician",
  "created_at": "2026-02-15T15:30:00Z",
  "updated_at": "2026-02-15T16:00:00Z"
}
```

**Error Responses:**
- **403** - User doesn't have permission to view this review
- **404** - Booking or review not found

---

### 4. Respond to Review (Artisan)

**Endpoint:** `PATCH /reviews/{review_id}/respond`

**Authentication:** Required (Artisan only)

**Request Body:**
```json
{
  "artisan_response": "Thank you for the kind words! It was a pleasure working with you."
}
```

**Field Requirements:**
- `artisan_response`: Required, string (10-500 characters)

**Success Response (200):**
```json
{
  "id": 1,
  "booking_id": 1,
  "rating": 4.5,
  "review_text": "Excellent service!",
  "artisan_response": "Thank you for the kind words! It was a pleasure working with you.",
  "artisan_responded_at": "2026-02-15T16:00:00Z",
  ...
}
```

**Error Responses:**
- **403** - Only the reviewed artisan can respond
- **404** - Review not found

---

### 5. Get Artisan Review Statistics

**Endpoint:** `GET /reviews/artisan/{artisan_id}/stats`

**Authentication:** Not required (public)

**Success Response (200):**
```json
{
  "artisan_id": "artisan-uuid",
  "total_reviews": 25,
  "average_rating": 4.3,
  "rating_distribution": {
    "1": 0,
    "2": 1,
    "3": 3,
    "4": 8,
    "5": 13
  },
  "total_jobs_completed": 30
}
```

**Error Responses:**
- **404** - Artisan not found

---

## Additional Notes for Frontend Implementation

### Booking, Payment & Review Module

18. **Booking References:** Format is "BK-YYYY-NNNNNN" (e.g., BK-2026-000001)
19. **Payment References:** Format is "PAY-YYYY-NNNNNN" (e.g., PAY-2026-000001)
20. **Decimal Values:** All money fields (budget, agreed_amount, amount) are returned as strings (e.g., "7500.00")
21. **Coordinates:** Job location uses PostGIS POINT, latitude and longitude are extracted separately
22. **Completion Images:** Stored as JSON array, parsed automatically in responses
23. **Status Checks:** Always verify booking status before allowing actions (e.g., can't start an unpaid booking)
24. **Paystack Integration:** Test with Paystack test keys and test cards before going live
25. **Review Ratings:** Must be in 0.5 increments (1.0, 1.5, 2.0, 2.5, 3.0, 3.5, 4.0, 4.5, 5.0)
26. **Webhook Security:** Paystack webhooks are signature-verified (HMAC SHA512)
27. **Anonymous Reviews:** When is_anonymous is true, customer_name returns null
28. **Payment Flow:** Customer → Paystack checkout → Webhook updates status → Artisan gets notified
29. **Cancellation Policy:** Bookings can only be cancelled before payment (PENDING or ACCEPTED status)
30. **Review Period:** Reviews can only be created after booking status is COMPLETED

### Wallet Module

31. **Artisan Only:** All wallet endpoints require artisan authentication
32. **Real-Time Balance:** Wallet balance is calculated dynamically from payment records, not stored separately
33. **Pending vs Released:** Pending shows funds held in escrow (SUCCESS status), Released shows actual payouts (RELEASED status)
34. **No Separate Wallet Table:** Wallet data is derived from Payment and Booking tables
35. **Payment Flow:** Customer pays → SUCCESS (held by Paystack) → Job completed → RELEASED (paid to artisan)
36. **Earnings History:** Shows all payments with full booking context for easy tracking
37. **Payout History:** Shows only completed payouts that artisan has received
38. **Stats Calculation:** Only includes successful and released payments in statistics
39. **Minimum Payout:** ₦5,000 minimum payout amount enforced
40. **Payout Request:** Artisans can request withdrawal of available balance to their bank account
41. **Bank Verification:** Bank accounts are verified via Paystack before processing payouts
42. **Payout Processing:** Payments are released in chronological order to fulfill requested amount
43. **Available Balance:** Only SUCCESS status payments (paid but not yet released) can be withdrawn
44. **Bank Codes:** Use official Nigerian bank codes (057 for Zenith, 044 for Access, etc.)

---

## TODO / Coming Soon

- Google OAuth implementation
- Chat messaging endpoints
- Push notifications endpoints
- Admin endpoints for managing bookings/disputes

---

**Last Updated:** 2026-02-05
**API Version:** v1
