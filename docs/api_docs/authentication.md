# Authentication API Documentation

## Overview
Authentication flow supports both Artisan and Client user types with multi-step registration and password recovery.

---

## 1. User Registration

### Step 1: Submit Personal Information
**Endpoint:** `POST /auth/register/personal-info`

**Request Body:**
```json
{
  "full_name": "string",
  "email": "string",
  "phone_number": "string",
  "user_type": "artisan | client"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Personal information saved successfully",
  "user_id": "string"
}
```

**Notes:**
- Email validation: must contain `@`
- `user_type` can be either `"artisan"` or `"client"`

---

### Step 2: Set Password
**Endpoint:** `POST /auth/register/password`

**Request Body:**
```json
{
  "user_id": "string",
  "password": "string",
  "confirm_password": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Password set successfully"
}
```

**Validation:**
- Password must be at least 8 characters
- `password` and `confirm_password` must match

---

### Step 3: Verify Email
**Endpoint:** `POST /auth/register/send-otp`

**Request Body:**
```json
{
  "user_id": "string",
  "email": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "OTP sent successfully"
}
```

---

**Endpoint:** `POST /auth/register/verify-otp`

**Request Body:**
```json
{
  "user_id": "string",
  "otp_code": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Email verified successfully"
}
```

**Notes:**
- OTP code is 6 digits
- OTP is sent to the email address provided during registration

---

### Step 4: Select Services
**Endpoint:** `POST /auth/register/services`

**Request Body:**
```json
{
  "user_id": "string",
  "user_type": "artisan | client",
  "services": ["string"]
}
```

**Client Services Options:**
- Construction
- Car repairs/parts
- Electronics/repairs
- Dry Cleaning
- Electrical
- Fashion Design

**Artisan Services Options:**
- Electrician
- Plumber
- Carpenter
- Cleaner
- Painter
- Make up artist

**Response:**
```json
{
  "success": true,
  "message": "Services saved successfully"
}
```

**Validation:**
- At least one service must be selected
- Services list should contain service titles as strings

---

### Step 5: Upload Profile Picture & Bio
**Endpoint:** `POST /auth/register/profile`

**Request Body (multipart/form-data):**
```
user_id: string
profile_picture: file (optional)
bio: string (optional)
```

**Response:**
```json
{
  "success": true,
  "message": "Registration completed successfully",
  "user": {
    "id": "string",
    "full_name": "string",
    "email": "string",
    "phone_number": "string",
    "user_type": "artisan | client",
    "profile_picture_url": "string | null",
    "bio": "string | null"
  }
}
```

**Notes:**
- Profile picture and bio are optional
- Profile picture should be image format (jpg, png)
- Max image size: 1080x1080 pixels

---

## 2. Login

### Standard Login
**Endpoint:** `POST /auth/login`

**Request Body:**
```json
{
  "email": "string",
  "password": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Login successful",
  "token": "string",
  "user": {
    "id": "string",
    "full_name": "string",
    "email": "string",
    "user_type": "artisan | client",
    "profile_picture_url": "string | null"
  }
}
```

**Error Response:**
```json
{
  "success": false,
  "message": "Invalid email or password"
}
```

---

### Google Sign-In
**Endpoint:** `POST /auth/google`

**Request Body:**
```json
{
  "google_token": "string",
  "user_type": "artisan | client"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Google sign-in successful",
  "token": "string",
  "is_new_user": boolean,
  "user": {
    "id": "string",
    "full_name": "string",
    "email": "string",
    "user_type": "artisan | client",
    "profile_picture_url": "string | null"
  }
}
```

**Notes:**
- If `is_new_user: true`, redirect to service selection flow
- If `is_new_user: false`, proceed to home screen

---

## 3. Password Recovery

### Step 1: Request Reset Code
**Endpoint:** `POST /auth/forgot-password/send-code`

**Request Body:**
```json
{
  "email": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Reset code sent to email"
}
```

**Notes:**
- Send 6-digit OTP code to user's email

---

### Step 2: Verify Reset Code
**Endpoint:** `POST /auth/forgot-password/verify-code`

**Request Body:**
```json
{
  "email": "string",
  "code": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Code verified successfully",
  "reset_token": "string"
}
```

**Notes:**
- Code is 6 digits
- Include resend functionality with cooldown timer

---

### Step 3: Reset Password
**Endpoint:** `POST /auth/forgot-password/reset`

**Request Body:**
```json
{
  "email": "string",
  "reset_token": "string",
  "new_password": "string",
  "confirm_password": "string"
}
```

**Response:**
```json
{
  "success": true,
  "message": "Password reset successful"
}
```

**Validation:**
- Password must be at least 8 characters
- `new_password` and `confirm_password` must match

---

## 4. Resend OTP
**Endpoint:** `POST /auth/resend-otp`

**Request Body:**
```json
{
  "email": "string",
  "type": "phone_verification | password_reset"
}
```

**Response:**
```json
{
  "success": true,
  "message": "OTP resent successfully",
  "retry_after": 60
}
```

**Notes:**
- `retry_after` indicates cooldown period in seconds
- Default cooldown: 60 seconds

---

## Error Codes

| Code | Message |
|------|---------|
| 400 | Invalid request parameters |
| 401 | Unauthorized - Invalid credentials |
| 404 | User not found |
| 409 | Email or phone already exists |
| 422 | Validation error |
| 429 | Too many requests - Rate limited |
| 500 | Internal server error |

---

## Notes
- All endpoints should use HTTPS
- Token authentication required for protected routes
- Store tokens securely on client side
- OTP codes expire after 10 minutes
- Phone verification is mandatory before proceeding to service selection
