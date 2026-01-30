# Quick Test Guide

## Test Account Credentials
**Password for all accounts:** `Test123!`

## Quick Test Commands

### 1. Test Services Endpoint
```bash
curl 'http://localhost:8000/api/v1/services?limit=5'
```
Expected: Returns 5 services with images

### 2. Search All Artisans (No Filters)
```bash
curl 'http://localhost:8000/api/v1/search/artisans?latitude=6.5244&longitude=3.3792&radius_km=50'
```
Expected: 10 artisans total

### 3. Search Verified Artisans Only
```bash
curl 'http://localhost:8000/api/v1/search/artisans?latitude=6.5244&longitude=3.3792&radius_km=50&verified_only=true'
```
Expected: 5 verified artisans

### 4. Search by Service (Electrician & Plumbing)
```bash
curl 'http://localhost:8000/api/v1/search/artisans?latitude=6.5244&longitude=3.3792&radius_km=50&service_ids=14,15'
```
Expected: 2 artisans (John Electrician, Sarah Plumber)

### 5. Search by Single Service (Carpentry)
```bash
curl 'http://localhost:8000/api/v1/search/artisans?latitude=6.5244&longitude=3.3792&radius_km=50&service_ids=16'
```
Expected: 1 artisan (David Carpenter)

### 6. Database Quick Check
```bash
docker exec workchop-api_db psql -U user -d workchop_db -c "SELECT email, full_name, user_type FROM users WHERE email LIKE '%@test.com' ORDER BY email LIMIT 5;"
```

## Test Account Logins

### Verified Artisans
- artisan1@test.com (John Electrician)
- artisan2@test.com (Sarah Plumber)
- artisan3@test.com (David Carpenter)
- artisan4@test.com (Grace Painter)
- artisan5@test.com (Michael Mechanic)

### Unverified Artisans
- artisan6@test.com (Mary Cleaner)
- artisan7@test.com (James Tailor)
- artisan8@test.com (Lucy Hairstylist)
- artisan9@test.com (Peter Constructor)
- artisan10@test.com (Rita Electronics)

### Clients
- client1@test.com (Alice Customer)
- client2@test.com (Bob Johnson)
- client3@test.com (Carol Williams)
- ... (see test_accounts.txt for full list)

## Service IDs for Testing
- 14: Electrician
- 15: Plumbing
- 16: Carpentry
- 17: Cleaning
- 18: Painting
- 19: Beauty/Makeup
- 20: Construction
- 21: Auto Repair
- 22: Electronics Repair
- 23: Dry Cleaning
- 24: Fashion/Tailoring
- 25: Home Repair

## Re-create Test Accounts
```bash
docker exec workchop-api_api python scripts/create_test_accounts.py
```

## Check API Logs
```bash
docker logs workchop-api_api --tail 50
```

## Restart API
```bash
docker restart workchop-api_api
```
