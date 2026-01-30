"""
Email sending utilities with SMTP support and HTML templates.
"""
import smtplib
import asyncio
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from pathlib import Path
from typing import Optional
from jinja2 import Environment, FileSystemLoader, select_autoescape

from app.core.logger import logger
from app.core.config import settings


# Setup Jinja2 template environment
templates_dir = Path(__file__).parent.parent / "templates" / "emails"
jinja_env = Environment(
    loader=FileSystemLoader(templates_dir),
    autoescape=select_autoescape(['html', 'xml'])
)


def render_template(template_name: str, **context) -> str:
    """
    Render email template with context.

    Args:
        template_name: Name of template file
        **context: Template context variables

    Returns:
        Rendered HTML string
    """
    try:
        template = jinja_env.get_template(template_name)
        return template.render(**context)
    except Exception as e:
        logger.error(f"Failed to render template {template_name}: {str(e)}")
        raise


def send_email_smtp(
    to_email: str,
    subject: str,
    html_content: str,
    text_content: Optional[str] = None
) -> bool:
    """
    Send email using SMTP.

    Args:
        to_email: Recipient email address
        subject: Email subject
        html_content: HTML email body
        text_content: Plain text email body (fallback)

    Returns:
        True if sent successfully, False otherwise
    """
    # Check if SMTP is configured
    if not settings.SMTP_HOST or not settings.SMTP_USER or not settings.SMTP_PASSWORD:
        logger.warning(
            f"SMTP not configured - Email would be sent to {to_email} with subject: {subject}"
        )
        # In development, log the email instead of failing
        if settings.ENVIRONMENT == "development":
            logger.info(f"[DEV MODE] Email Preview:\nTo: {to_email}\nSubject: {subject}")
            return True
        return False

    try:
        # Create message
        message = MIMEMultipart("alternative")
        message["From"] = f"{settings.EMAILS_FROM_NAME} <{settings.EMAILS_FROM_EMAIL}>"
        message["To"] = to_email
        message["Subject"] = subject

        # Add plain text version (fallback)
        if text_content:
            text_part = MIMEText(text_content, "plain")
            message.attach(text_part)

        # Add HTML version
        html_part = MIMEText(html_content, "html")
        message.attach(html_part)

        # Connect to SMTP server and send
        if settings.SMTP_TLS:
            server = smtplib.SMTP(settings.SMTP_HOST, settings.SMTP_PORT)
            server.starttls()
        else:
            server = smtplib.SMTP_SSL(settings.SMTP_HOST, settings.SMTP_PORT)

        server.login(settings.SMTP_USER, settings.SMTP_PASSWORD)
        server.sendmail(settings.EMAILS_FROM_EMAIL, to_email, message.as_string())
        server.quit()

        logger.info(f"Email sent successfully to {to_email}")
        return True

    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False


async def send_otp_email(email: str, otp_code: str, purpose: str = "verification") -> bool:
    """
    Send OTP code via email (async).

    Args:
        email: Recipient email address
        otp_code: The 6-digit OTP code
        purpose: Purpose of OTP (verification or password_reset)

    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        # Determine subject and message based on purpose
        if purpose == "password_reset":
            subject = "Password Reset Code - Workchop"
            title = "Reset Your Password"
            message = "Use the code below to reset your password:"
        else:
            subject = "Verify Your Email - Workchop"
            title = "Verify Your Email Address"
            message = "Please enter this code to verify your email address:"

        # Render HTML template
        html_content = render_template(
            "otp.html" if purpose != "password_reset" else "password_reset.html",
            title=title,
            message=message,
            otp_code=otp_code
        )

        # Plain text fallback
        text_content = f"""
{title}

{message}

Your code is: {otp_code}

This code expires in 10 minutes.

If you didn't request this code, please ignore this email.

---
Workchop Team
"""

        # Run SMTP in thread pool to avoid blocking
        return await asyncio.to_thread(send_email_smtp, email, subject, html_content, text_content)

    except Exception as e:
        logger.error(f"Failed to send OTP email to {email}: {str(e)}")
        return False


async def send_password_reset_email(email: str, reset_token: str) -> bool:
    """
    Send password reset email (async).
    Note: This sends an OTP code, not a reset link.

    Args:
        email: Recipient email address
        reset_token: Password reset OTP code

    Returns:
        True if email sent successfully, False otherwise
    """
    return await send_otp_email(email, reset_token, purpose="password_reset")


async def send_welcome_email(email: str, full_name: str) -> bool:
    """
    Send welcome email after successful registration (async).

    Args:
        email: Recipient email address
        full_name: User's full name

    Returns:
        True if email sent successfully, False otherwise
    """
    try:
        subject = "Welcome to Workchop! 🎉"

        # Render HTML template
        html_content = render_template(
            "welcome.html",
            full_name=full_name
        )

        # Plain text fallback
        text_content = f"""
Welcome to Workchop!

Hi {full_name},

Your registration is complete! We're excited to have you join the Workchop community.

What you can do:
- Find skilled artisans near you
- Chat directly with professionals
- Pay securely with our escrow system
- Read ratings and reviews from real customers

Need help? Contact our support team at support@workchop.ng

---
Workchop Team
"""

        # Run SMTP in thread pool to avoid blocking
        return await asyncio.to_thread(send_email_smtp, email, subject, html_content, text_content)

    except Exception as e:
        logger.error(f"Failed to send welcome email to {email}: {str(e)}")
        return False


def send_booking_notification(
    email: str,
    full_name: str,
    booking_id: str,
    service_name: str,
    status: str
) -> bool:
    """
    Send booking status notification email.

    Args:
        email: Recipient email address
        full_name: User's full name
        booking_id: Booking ID
        service_name: Name of service
        status: Booking status (accepted, completed, cancelled, etc.)

    Returns:
        True if sent successfully, False otherwise
    """
    try:
        subject = f"Booking {status.capitalize()} - Workchop"

        # Simple HTML (can create a dedicated template later)
        html_content = f"""
<!DOCTYPE html>
<html>
<head>
    <style>
        body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; }}
        .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
        .header {{ background-color: #4F46E5; color: white; padding: 20px; text-align: center; }}
        .content {{ padding: 30px; background-color: #f9f9f9; }}
        .booking-info {{ background-color: white; padding: 15px; margin: 20px 0; border-radius: 5px; }}
    </style>
</head>
<body>
    <div class="container">
        <div class="header">
            <h2>Workchop</h2>
        </div>
        <div class="content">
            <p>Hi {full_name},</p>
            <p>Your booking has been {status}.</p>
            <div class="booking-info">
                <strong>Booking ID:</strong> {booking_id}<br>
                <strong>Service:</strong> {service_name}<br>
                <strong>Status:</strong> {status.upper()}
            </div>
            <p>You can view the full details in your Workchop app.</p>
        </div>
    </div>
</body>
</html>
"""

        text_content = f"""
Hi {full_name},

Your booking has been {status}.

Booking ID: {booking_id}
Service: {service_name}
Status: {status.upper()}

You can view the full details in your Workchop app.

---
Workchop Team
"""

        return send_email_smtp(email, subject, html_content, text_content)

    except Exception as e:
        logger.error(f"Failed to send booking notification to {email}: {str(e)}")
        return False
