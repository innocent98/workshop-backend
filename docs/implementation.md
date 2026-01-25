Implementation Roadmap - Workchop Backend                                                                                                                                               
                                                                                                                                                                                          
  Based on the PRD and existing auth implementation, here's my proposed module-by-module implementation plan:                                                                             
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 0: Infrastructure Setup (Week 1)                                                                                                                                                  
                                                                                                                                                                                          
  Task 0.1: Set up Celery for Background Tasks                                                                                                                                            
                                                                                                                                                                                          
  What we need:                                                                                                                                                                           
  - Celery worker configuration                                                                                                                                                           
  - Redis as message broker                                                                                                                                                               
  - Task definitions for email sending                                                                                                                                                    
  - Periodic tasks (reminders, cleanup)                                                                                                                                                   
                                                                                                                                                                                          
  Files to create:                                                                                                                                                                        
  - app/celery_app.py - Celery instance                                                                                                                                                   
  - app/tasks/email_tasks.py - Email sending tasks                                                                                                                                        
  - app/tasks/notification_tasks.py - Notification tasks                                                                                                                                  
  - docker-compose.yml update (add celery worker)                                                                                                                                         
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Task 0.2: Add PostGIS Extension                                                                                                                                                         
                                                                                                                                                                                          
  What we need:                                                                                                                                                                           
  - PostgreSQL PostGIS extension for location queries                                                                                                                                     
  - Migration to enable PostGIS                                                                                                                                                           
  - Location-based query utilities                                                                                                                                                        
                                                                                                                                                                                          
  Files to create:                                                                                                                                                                        
  - Alembic migration: add_postgis_extension                                                                                                                                              
  - app/utils/location.py - Distance calculation helpers                                                                                                                                  
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Task 0.3: Integrate Cloudinary                                                                                                                                                          
                                                                                                                                                                                          
  What we need:                                                                                                                                                                           
  - Cloudinary SDK setup                                                                                                                                                                  
  - Replace local file storage with cloud upload                                                                                                                                          
  - Environment variables for Cloudinary config                                                                                                                                           
                                                                                                                                                                                          
  Files to modify:                                                                                                                                                                        
  - app/utils/file_upload.py - Add Cloudinary upload                                                                                                                                      
  - app/core/config.py - Add Cloudinary settings                                                                                                                                          
  - .env.example - Add Cloudinary vars                                                                                                                                                    
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Task 0.4: Implement Real Email Service                                                                                                                                                  
                                                                                                                                                                                          
  What we need:                                                                                                                                                                           
  - Replace placeholder email functions                                                                                                                                                   
  - HTML email templates with Jinja2                                                                                                                                                      
  - Email task queue with Celery                                                                                                                                                          
                                                                                                                                                                                          
  Files to modify:                                                                                                                                                                        
  - app/utils/email.py - Implement real sending                                                                                                                                           
  - Create app/templates/emails/ directory                                                                                                                                                
  - Email templates: otp.html, welcome.html, password_reset.html                                                                                                                          
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 1: Service Categories & Profile Management (Week 2)                                                                                                                               
                                                                                                                                                                                          
  Module 1: Service Categories Management                                                                                                                                                 
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  # Already exists: Service model                                                                                                                                                         
  # Need to add:                                                                                                                                                                          
  - ServiceCategory (Plumbing, Electrical, etc.)                                                                                                                                          
  - ServiceSubcategory (Kitchen plumbing, Bathroom plumbing)                                                                                                                              
  - Update Service model to link to categories                                                                                                                                            
                                                                                                                                                                                          
  Endpoints to create:                                                                                                                                                                    
  GET /api/v1/services/categories - List all categories                                                                                                                                   
  GET /api/v1/services/categories/{id}/services - Services in a category                                                                                                                  
  GET /api/v1/services - List all available services                                                                                                                                      
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/service_category.py                                                                                                                                                
  - Modify: app/db/models/service.py                                                                                                                                                      
  - New: app/schemas/service.py                                                                                                                                                           
  - New: app/api/v1/endpoints/services.py                                                                                                                                                 
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Module 2: Profile Management                                                                                                                                                            
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  # Need to add:                                                                                                                                                                          
  - ArtisanProfile (extends User data)                                                                                                                                                    
    - service_radius (km)                                                                                                                                                                 
    - hourly_rate_min, hourly_rate_max                                                                                                                                                    
    - years_of_experience                                                                                                                                                                 
    - is_verified (admin approval)                                                                                                                                                        
    - verification_documents (JSON array of URLs)                                                                                                                                         
    - availability_status (AVAILABLE|BUSY|OFFLINE)                                                                                                                                        
    - average_rating                                                                                                                                                                      
    - total_jobs_completed                                                                                                                                                                
    - response_time_avg (minutes)                                                                                                                                                         
                                                                                                                                                                                          
  - Portfolio (artisan work samples)                                                                                                                                                      
    - artisan_id                                                                                                                                                                          
    - image_url                                                                                                                                                                           
    - title, description                                                                                                                                                                  
    - created_at                                                                                                                                                                          
                                                                                                                                                                                          
  - ArtisanServiceArea (geofencing - PostGIS)                                                                                                                                             
    - artisan_id                                                                                                                                                                          
    - service_location (PostGIS GEOGRAPHY type)                                                                                                                                           
    - radius_km                                                                                                                                                                           
                                                                                                                                                                                          
  Endpoints to create:                                                                                                                                                                    
  # Customer endpoints                                                                                                                                                                    
  GET /api/v1/customers/me - Get my profile                                                                                                                                               
  PUT /api/v1/customers/me - Update my profile                                                                                                                                            
                                                                                                                                                                                          
  # Artisan endpoints                                                                                                                                                                     
  GET /api/v1/artisans/me - Get my artisan profile                                                                                                                                        
  PUT /api/v1/artisans/me - Update profile                                                                                                                                                
  PATCH /api/v1/artisans/me/availability - Toggle availability                                                                                                                            
  POST /api/v1/artisans/me/portfolio - Add portfolio item                                                                                                                                 
  DELETE /api/v1/artisans/me/portfolio/{id} - Delete portfolio item                                                                                                                       
  GET /api/v1/artisans/me/stats - Get my statistics                                                                                                                                       
                                                                                                                                                                                          
  # Public endpoints                                                                                                                                                                      
  GET /api/v1/artisans/{id} - View artisan public profile                                                                                                                                 
  GET /api/v1/artisans/{id}/portfolio - View artisan portfolio                                                                                                                            
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/artisan_profile.py                                                                                                                                                 
  - New: app/db/models/portfolio.py                                                                                                                                                       
  - New: app/schemas/profile.py                                                                                                                                                           
  - New: app/schemas/portfolio.py                                                                                                                                                         
  - New: app/api/v1/endpoints/profile.py                                                                                                                                                  
  - New: app/services/profile.py                                                                                                                                                          
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 2: Location & Search (Week 3)                                                                                                                                                     
                                                                                                                                                                                          
  Module 3: Location-Based Search                                                                                                                                                         
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  # Already handled in ArtisanProfile                                                                                                                                                     
  # Add location utilities                                                                                                                                                                
                                                                                                                                                                                          
  Endpoints to create:                                                                                                                                                                    
  GET /api/v1/artisans/search                                                                                                                                                             
    Query params:                                                                                                                                                                         
    - category_id                                                                                                                                                                         
    - service_ids (comma-separated)                                                                                                                                                       
    - lat, lng (required)                                                                                                                                                                 
    - radius (km, default 10)                                                                                                                                                             
    - budget_min, budget_max                                                                                                                                                              
    - min_rating                                                                                                                                                                          
    - verified_only (boolean)                                                                                                                                                             
    - availability (AVAILABLE|BUSY)                                                                                                                                                       
    - sort (distance|rating|price)                                                                                                                                                        
                                                                                                                                                                                          
  GET /api/v1/artisans/nearby                                                                                                                                                             
    Query params:                                                                                                                                                                         
    - lat, lng (required)                                                                                                                                                                 
    - radius (default 5km)                                                                                                                                                                
    - limit (default 10)                                                                                                                                                                  
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/services/search.py                                                                                                                                                           
  - New: app/api/v1/endpoints/search.py                                                                                                                                                   
  - Modify: app/utils/location.py - Add PostGIS queries                                                                                                                                   
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 3: Booking System (Week 4)                                                                                                                                                        
                                                                                                                                                                                          
  Module 4: Core Booking Flow                                                                                                                                                             
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  - Booking                                                                                                                                                                               
    - id (UUID)                                                                                                                                                                           
    - customer_id (FK → User)                                                                                                                                                             
    - artisan_id (FK → User)                                                                                                                                                              
    - service_id (FK → Service)                                                                                                                                                           
    - status (PENDING|ACCEPTED|REJECTED|IN_PROGRESS|COMPLETED|CANCELLED)                                                                                                                  
    - scheduled_date, scheduled_time                                                                                                                                                      
    - location_address (text)                                                                                                                                                             
    - location_lat, location_lng (PostGIS POINT)                                                                                                                                          
    - budget_min, budget_max                                                                                                                                                              
    - agreed_price (set when artisan accepts)                                                                                                                                             
    - customer_notes (optional description)                                                                                                                                               
    - artisan_notes (optional)                                                                                                                                                            
    - created_at, updated_at                                                                                                                                                              
                                                                                                                                                                                          
  - BookingStatusHistory (audit trail)                                                                                                                                                    
    - booking_id                                                                                                                                                                          
    - old_status, new_status                                                                                                                                                              
    - changed_by (user_id)                                                                                                                                                                
    - changed_at                                                                                                                                                                          
    - notes                                                                                                                                                                               
                                                                                                                                                                                          
  Endpoints to create:                                                                                                                                                                    
  # Customer endpoints                                                                                                                                                                    
  POST /api/v1/bookings - Create booking request                                                                                                                                          
  GET /api/v1/bookings - List my bookings (customer view)                                                                                                                                 
  GET /api/v1/bookings/{id} - Get booking details                                                                                                                                         
  PATCH /api/v1/bookings/{id}/cancel - Cancel booking                                                                                                                                     
                                                                                                                                                                                          
  # Artisan endpoints                                                                                                                                                                     
  GET /api/v1/artisans/me/bookings - List my job requests                                                                                                                                 
  GET /api/v1/artisans/me/bookings?status=pending - Filter by status                                                                                                                      
  POST /api/v1/artisans/me/bookings/{id}/accept - Accept job                                                                                                                              
  POST /api/v1/artisans/me/bookings/{id}/reject - Reject job                                                                                                                              
  PATCH /api/v1/artisans/me/bookings/{id}/start - Mark job as in progress                                                                                                                 
  PATCH /api/v1/artisans/me/bookings/{id}/complete - Mark job complete                                                                                                                    
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/booking.py                                                                                                                                                         
  - New: app/schemas/booking.py                                                                                                                                                           
  - New: app/services/booking.py                                                                                                                                                          
  - New: app/api/v1/endpoints/bookings.py                                                                                                                                                 
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 4: Payments & Wallet (Week 5)                                                                                                                                                     
                                                                                                                                                                                          
  Module 5: Paystack Integration & Wallet                                                                                                                                                 
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  - Wallet                                                                                                                                                                                
    - user_id (FK → User, unique)                                                                                                                                                         
    - balance (Decimal)                                                                                                                                                                   
    - total_earned (for artisans)                                                                                                                                                         
    - total_spent (for customers)                                                                                                                                                         
    - currency (NGN)                                                                                                                                                                      
    - updated_at                                                                                                                                                                          
                                                                                                                                                                                          
  - Transaction                                                                                                                                                                           
    - id (UUID)                                                                                                                                                                           
    - wallet_id (FK → Wallet)                                                                                                                                                             
    - booking_id (FK → Booking, nullable)                                                                                                                                                 
    - type (CREDIT|DEBIT|WITHDRAWAL|REFUND)                                                                                                                                               
    - amount (Decimal)                                                                                                                                                                    
    - currency (NGN)                                                                                                                                                                      
    - status (PENDING|SUCCESS|FAILED)                                                                                                                                                     
    - payment_method (CARD|BANK_TRANSFER|WALLET)                                                                                                                                          
    - reference (unique, for Paystack)                                                                                                                                                    
    - metadata (JSON)                                                                                                                                                                     
    - created_at                                                                                                                                                                          
                                                                                                                                                                                          
  - PaystackPayment                                                                                                                                                                       
    - transaction_id (FK → Transaction)                                                                                                                                                   
    - paystack_reference                                                                                                                                                                  
    - authorization_code (for recurring)                                                                                                                                                  
    - payment_channel                                                                                                                                                                     
    - customer_email                                                                                                                                                                      
    - paid_at                                                                                                                                                                             
    - paystack_response (JSON)                                                                                                                                                            
                                                                                                                                                                                          
  - Withdrawal                                                                                                                                                                            
    - id (UUID)                                                                                                                                                                           
    - artisan_id (FK → User)                                                                                                                                                              
    - amount                                                                                                                                                                              
    - status (PENDING|PROCESSING|COMPLETED|REJECTED)                                                                                                                                      
    - bank_account_id (FK)                                                                                                                                                                
    - transaction_id (FK → Transaction, nullable)                                                                                                                                         
    - requested_at, processed_at                                                                                                                                                          
    - admin_notes                                                                                                                                                                         
                                                                                                                                                                                          
  Endpoints to create:                                                                                                                                                                    
  # Customer payment endpoints                                                                                                                                                            
  POST /api/v1/payments/initialize - Initialize Paystack payment                                                                                                                          
  POST /api/v1/payments/verify/{reference} - Verify payment                                                                                                                               
  GET /api/v1/wallets/me - Get my wallet                                                                                                                                                  
  GET /api/v1/transactions - Get my transactions                                                                                                                                          
                                                                                                                                                                                          
  # Artisan endpoints                                                                                                                                                                     
  GET /api/v1/artisans/me/earnings - Get earnings summary                                                                                                                                 
  POST /api/v1/artisans/me/withdrawals - Request withdrawal                                                                                                                               
  GET /api/v1/artisans/me/withdrawals - List withdrawal requests                                                                                                                          
                                                                                                                                                                                          
  # Webhooks                                                                                                                                                                              
  POST /api/v1/webhooks/paystack - Paystack webhook handler                                                                                                                               
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/wallet.py                                                                                                                                                          
  - New: app/db/models/transaction.py                                                                                                                                                     
  - New: app/db/models/withdrawal.py                                                                                                                                                      
  - New: app/schemas/payment.py                                                                                                                                                           
  - New: app/services/payment.py                                                                                                                                                          
  - New: app/services/wallet.py                                                                                                                                                           
  - New: app/integrations/paystack.py                                                                                                                                                     
  - New: app/api/v1/endpoints/payments.py                                                                                                                                                 
  - New: app/api/v1/endpoints/webhooks.py                                                                                                                                                 
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 5: Ratings & Reviews (Week 6)                                                                                                                                                     
                                                                                                                                                                                          
  Module 6: Rating System                                                                                                                                                                 
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  - Review                                                                                                                                                                                
    - id (UUID)                                                                                                                                                                           
    - booking_id (FK → Booking, unique)                                                                                                                                                   
    - customer_id (FK → User)                                                                                                                                                             
    - artisan_id (FK → User)                                                                                                                                                              
    - rating (1-5)                                                                                                                                                                        
    - comment (text, nullable)                                                                                                                                                            
    - is_flagged (admin moderation)                                                                                                                                                       
    - created_at                                                                                                                                                                          
                                                                                                                                                                                          
  - ReviewFlag                                                                                                                                                                            
    - review_id (FK → Review)                                                                                                                                                             
    - flagged_by (user_id)                                                                                                                                                                
    - reason                                                                                                                                                                              
    - flagged_at                                                                                                                                                                          
                                                                                                                                                                                          
  Endpoints to create:                                                                                                                                                                    
  # Customer endpoints                                                                                                                                                                    
  POST /api/v1/bookings/{id}/review - Submit review                                                                                                                                       
  GET /api/v1/customers/me/reviews - My submitted reviews                                                                                                                                 
                                                                                                                                                                                          
  # Public endpoints                                                                                                                                                                      
  GET /api/v1/artisans/{id}/reviews - Get artisan reviews                                                                                                                                 
  GET /api/v1/artisans/{id}/reviews/summary - Rating summary stats                                                                                                                        
                                                                                                                                                                                          
  # Moderation                                                                                                                                                                            
  POST /api/v1/reviews/{id}/flag - Flag inappropriate review                                                                                                                              
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/review.py                                                                                                                                                          
  - New: app/schemas/review.py                                                                                                                                                            
  - New: app/services/review.py                                                                                                                                                           
  - New: app/api/v1/endpoints/reviews.py                                                                                                                                                  
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 6: Real-time Features (Week 7-8)                                                                                                                                                  
                                                                                                                                                                                          
  Module 7: In-App Chat (WebSocket)                                                                                                                                                       
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  - ChatRoom                                                                                                                                                                              
    - id (UUID)                                                                                                                                                                           
    - booking_id (FK → Booking, unique)                                                                                                                                                   
    - customer_id, artisan_id (FK → User)                                                                                                                                                 
    - status (ACTIVE|CLOSED)                                                                                                                                                              
    - created_at, closed_at                                                                                                                                                               
                                                                                                                                                                                          
  - ChatMessage                                                                                                                                                                           
    - id (UUID)                                                                                                                                                                           
    - chat_room_id (FK → ChatRoom)                                                                                                                                                        
    - sender_id (FK → User)                                                                                                                                                               
    - message_type (TEXT|IMAGE|FILE)                                                                                                                                                      
    - content (text)                                                                                                                                                                      
    - file_url (nullable)                                                                                                                                                                 
    - is_read (boolean)                                                                                                                                                                   
    - created_at                                                                                                                                                                          
                                                                                                                                                                                          
  WebSocket & Endpoints:                                                                                                                                                                  
  WebSocket: ws://localhost:8000/ws/chat/{booking_id}                                                                                                                                     
    - Requires JWT auth via query param or header                                                                                                                                         
    - Real-time bidirectional messaging                                                                                                                                                   
                                                                                                                                                                                          
  REST Endpoints:                                                                                                                                                                         
  GET /api/v1/chat/{booking_id} - Get chat room                                                                                                                                           
  GET /api/v1/chat/{booking_id}/messages - Get message history                                                                                                                            
  POST /api/v1/chat/{booking_id}/messages - Send message (REST fallback)                                                                                                                  
  PATCH /api/v1/chat/{booking_id}/read - Mark messages as read                                                                                                                            
  POST /api/v1/chat/{booking_id}/upload - Upload file/image                                                                                                                               
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/chat.py                                                                                                                                                            
  - New: app/schemas/chat.py                                                                                                                                                              
  - New: app/services/chat.py                                                                                                                                                             
  - New: app/api/v1/endpoints/chat.py                                                                                                                                                     
  - New: app/websocket/chat.py - WebSocket handlers                                                                                                                                       
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Module 8: Push Notifications (FCM)                                                                                                                                                      
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  - DeviceToken                                                                                                                                                                           
    - id (UUID)                                                                                                                                                                           
    - user_id (FK → User)                                                                                                                                                                 
    - token (unique)                                                                                                                                                                      
    - platform (IOS|ANDROID)                                                                                                                                                              
    - is_active (boolean)                                                                                                                                                                 
    - created_at, updated_at                                                                                                                                                              
                                                                                                                                                                                          
  - Notification                                                                                                                                                                          
    - id (UUID)                                                                                                                                                                           
    - user_id (FK → User)                                                                                                                                                                 
    - type (JOB_ACCEPTED|PAYMENT_CONFIRMED|etc.)                                                                                                                                          
    - title, body                                                                                                                                                                         
    - data (JSON - extra payload)                                                                                                                                                         
    - is_read (boolean)                                                                                                                                                                   
    - created_at, read_at                                                                                                                                                                 
                                                                                                                                                                                          
  Endpoints to create:                                                                                                                                                                    
  POST /api/v1/notifications/register-device - Register FCM token                                                                                                                         
  DELETE /api/v1/notifications/device/{token} - Unregister device                                                                                                                         
  GET /api/v1/notifications - Get my notifications                                                                                                                                        
  PATCH /api/v1/notifications/{id}/read - Mark as read                                                                                                                                    
  PATCH /api/v1/notifications/read-all - Mark all as read                                                                                                                                 
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/notification.py                                                                                                                                                    
  - New: app/schemas/notification.py                                                                                                                                                      
  - New: app/services/notification.py                                                                                                                                                     
  - New: app/integrations/fcm.py                                                                                                                                                          
  - New: app/api/v1/endpoints/notifications.py                                                                                                                                            
  - New: app/tasks/notification_tasks.py - Celery tasks                                                                                                                                   
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Phase 7: Support & Settings (Week 9)                                                                                                                                                    
                                                                                                                                                                                          
  Module 9: Support System                                                                                                                                                                
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  - FAQ                                                                                                                                                                                   
    - id                                                                                                                                                                                  
    - question, answer                                                                                                                                                                    
    - category (GENERAL|PAYMENTS|BOOKINGS)                                                                                                                                                
    - order (for sorting)                                                                                                                                                                 
    - is_active                                                                                                                                                                           
                                                                                                                                                                                          
  - SupportTicket                                                                                                                                                                         
    - id (UUID)                                                                                                                                                                           
    - user_id (FK → User)                                                                                                                                                                 
    - subject, description                                                                                                                                                                
    - status (OPEN|IN_PROGRESS|RESOLVED|CLOSED)                                                                                                                                           
    - priority (LOW|MEDIUM|HIGH)                                                                                                                                                          
    - created_at, updated_at, resolved_at                                                                                                                                                 
                                                                                                                                                                                          
  - SupportTicketMessage                                                                                                                                                                  
    - ticket_id (FK)                                                                                                                                                                      
    - sender_id (FK → User)                                                                                                                                                               
    - message                                                                                                                                                                             
    - created_at                                                                                                                                                                          
                                                                                                                                                                                          
  Endpoints:                                                                                                                                                                              
  GET /api/v1/support/faqs - List FAQs                                                                                                                                                    
  POST /api/v1/support/tickets - Create support ticket                                                                                                                                    
  GET /api/v1/support/tickets - My support tickets                                                                                                                                        
  GET /api/v1/support/tickets/{id} - Ticket details                                                                                                                                       
  POST /api/v1/support/tickets/{id}/messages - Reply to ticket                                                                                                                            
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/support.py                                                                                                                                                         
  - New: app/schemas/support.py                                                                                                                                                           
  - New: app/api/v1/endpoints/support.py                                                                                                                                                  
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Module 10: User Settings                                                                                                                                                                
                                                                                                                                                                                          
  Database Models:                                                                                                                                                                        
  - UserSettings                                                                                                                                                                          
    - user_id (FK → User, unique)                                                                                                                                                         
    - notification_preferences (JSON)                                                                                                                                                     
      - push_enabled                                                                                                                                                                      
      - email_enabled                                                                                                                                                                     
      - sms_enabled                                                                                                                                                                       
      - marketing_emails                                                                                                                                                                  
    - privacy_settings (JSON)                                                                                                                                                             
      - profile_visible                                                                                                                                                                   
      - show_phone_number                                                                                                                                                                 
    - updated_at                                                                                                                                                                          
                                                                                                                                                                                          
  - BankAccount (for artisan withdrawals)                                                                                                                                                 
    - id (UUID)                                                                                                                                                                           
    - artisan_id (FK → User)                                                                                                                                                              
    - account_name, account_number                                                                                                                                                        
    - bank_name, bank_code                                                                                                                                                                
    - is_primary (boolean)                                                                                                                                                                
    - is_verified (boolean)                                                                                                                                                               
    - created_at                                                                                                                                                                          
                                                                                                                                                                                          
  Endpoints:                                                                                                                                                                              
  GET /api/v1/settings - Get my settings                                                                                                                                                  
  PUT /api/v1/settings - Update settings                                                                                                                                                  
  PUT /api/v1/settings/notifications - Update notification preferences                                                                                                                    
  PUT /api/v1/settings/privacy - Update privacy settings                                                                                                                                  
                                                                                                                                                                                          
  POST /api/v1/settings/bank-accounts - Add bank account                                                                                                                                  
  GET /api/v1/settings/bank-accounts - List bank accounts                                                                                                                                 
  DELETE /api/v1/settings/bank-accounts/{id} - Remove bank account                                                                                                                        
  PATCH /api/v1/settings/bank-accounts/{id}/primary - Set as primary                                                                                                                      
                                                                                                                                                                                          
  Files:                                                                                                                                                                                  
  - New: app/db/models/settings.py                                                                                                                                                        
  - New: app/schemas/settings.py                                                                                                                                                          
  - New: app/api/v1/endpoints/settings.py                                                                                                                                                 
                                                                                                                                                                                          
  ---                                                                                                                                                                                     
  Summary of Implementation Order                                                                                                                                                         
                                                                                                                                                                                          
  1. Week 1: Infrastructure (Celery, PostGIS, Cloudinary, Real Email)                                                                                                                     
  2. Week 2: Services & Profiles                                                                                                                                                          
  3. Week 3: Location & Search                                                                                                                                                            
  4. Week 4: Booking System                                                                                                                                                               
  5. Week 5: Payments & Wallet                                                                                                                                                            
  6. Week 6: Ratings & Reviews                                                                                                                                                            
  7. Week 7-8: Chat & Notifications                                                                                                                                                       
  8. Week 9: Support & Settings                                                                                                                                                           
                                                                                                                                                                                          
  Would you like me to start with Phase 0 (Infrastructure Setup)? I recommend we begin by:                                                                                                
  1. Setting up Celery                                                                                                                                                                    
  2. Enabling PostGIS                                                                                                                                                                     
  3. Integrating Cloudinary                                                                                                                                                               
  4. Implementing real email service           