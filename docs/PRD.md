 Mobile App PRD – Workchop



 Platform Overview
Product Name: Workchop
Rebranding of: www.t-hub.com.ng
Platform: Android & iOS mobile app (Customer + Artisan) Website Purpose: Informational + App download links Region: Nigeria (Nationwide)
HQ: Lagos
Date: April 12, 2025
Version: 1.0

 User Roles

Role
Description
Customer
Books artisan services via the app
Artisan
Accepts jobs via mobile, manages schedule
Verified Pro
Artisan approved by admin with badge
Admin
Full access via web dashboard
Support Staff
Customer service and moderation via dashboard


 Modules & Mobile Features

Authentication (Mobile)
Goal: Easy and secure login/signup
 Sign-up via Phone Number, Email, Google  OTP Verification (SMS or Email)
 Role selection (Customer / Artisan)  Forgot password / reset flow
  Persistent login using token auth


User Stories:
  As a customer or artisan, I want to securely register and log in, so that I can access the platform’s features.
  As a customer, I want to verify my phone number via OTP, so that I can confirm my identity during sign-up.
  As an artisan, I want to select my service category during onboarding, so that I can tailor my profile.

Onboarding (App Guided)
Goal: Tailored onboarding with minimal typing  Role-based onboarding
  Customers: Select service, location, budget, schedule preference  Artisans: Select service types, add profile, upload verification
  Optional voice-based job input (voice-to-text)

Profile Management
  Editable profile (Name, Phone, Avatar, Bio)
 Artisan: Portfolio upload, service coverage radius  View booking history, earnings (for artisans)
 Change password, update contact info  Set “Available” / “Not Available” toggle

User Stories:
  As an artisan, I want to toggle my availability, so that I can focus on jobs without being overwhelmed.
  As an artisan, I want to edit my profile and upload my portfolio, so that potential customers can view my services.
  As a customer, I want to view my booking history, so that I can keep track of previous jobs.

Settings
  Language selector (English, Yoruba, Hausa, Igbo)  Push Notification preferences
  Payment settings (bank account, withdrawal threshold)  Privacy (visibility control for artisans)

Homepage (Customer View)

Mobile Layout
  Search bar: “What help do you need?”
  Location auto-detect with override option
 Category Carousel (Plumbing, AC repair, etc.)   “Schedule Service” Quick Button
  Nearby verified artisans slider
  “How it works” walkthrough modal
  CTA to chat with support if confused

User Stories:
  As a customer, I want to search for artisans based on proximity, pricing, and ratings, so that I can book the right professional for the job.
  As a customer, I want to view verified artisans near my location, so that I can choose trustworthy professionals.
  
Service Booking Flow Flow Summary:
Search or browse services
Set job date/time, address (use Google Maps API)
Set budget range (₦ slider or input)
View filtered artisans by availability, rating, pricing
Select artisan → send booking request
Artisan accepts → payment screen shows
User pays (deposit or full)
Artisan notified with job summary
After job → rating prompt appears

User Stories:
  As a customer, I want to set my preferred budget range, so that I can control costs.
  As a customer, I want to book artisans based on rating and pricing, so that I can trust their expertise.
  As a customer, I want to rate and review artisans after a job is completed, so that I can share my feedback for others.

Artisan Dashboard (Mobile)

  Job Requests (pending, accepted, completed)
 Earnings Wallet
  “Verified Pro” badge status
 Customer ratings & feedback  Availability toggle
  Response time stats (shown to users)

Artisan Directory Page (Mobile)
 Filters:
 Location proximity  Verified badge
 Price range  Availability  Ratings
  Tap on artisan → detailed profile
  “Book Now” or “Chat First” options

In-App Chat (Optional - Phase 2/3)
  Basic chat between artisan & customer after booking is sent  Auto-expire after job completion
  File/image support (for showing broken items or locations)

User Stories:
  As a customer, I want to chat with artisans before confirming bookings, so that I can discuss service details.

Payments & Wallet (Mobile)
  Accept: Debit Cards, Bank Transfer, In-App Wallet  Customer pays → Artisan receives post-completion  Escrow-style wallet system
  Admin panel controls release of funds
  Refund/cancel logic (job not done, late, etc.)

User Stories:
  As a customer, I want to make payments securely using my preferred method, so that I feel confident in transactions.
  As an artisan, I want to receive payments into my wallet post-job completion, so that I am assured fairness.

Ratings & Reviews
  Prompt after job is marked completed  1–5 stars + optional comment
  Filter abusive reviews via backend
  Display average ratings + badge info on profiles

Push Notifications
 Job accepted/rejected  Payment confirmation
 Appointment reminders  Review request
 Support messages

Support Module (App + Web)
  In-app Help → FAQ, “Talk to Support” (chat/email)   Admin dashboard manages tickets
  Flagged users or jobs trigger internal review

Admin Dashboard (Web Only)
  Manage users and artisans
 Verify artisans → assign badges  View and resolve disputes
  View job activity logs
  Analytics: Top cities, services, earnings
