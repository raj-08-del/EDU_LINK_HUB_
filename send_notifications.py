import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

def send_notification(subject, body, to_email):
    """
    Sends an email notification via Gmail SMTP.
    
    Args:
        subject (str): The subject of the email.
        body (str): The body content of the email.
        to_email (str): The recipient's email address.
    """
    # --- CONFIGURATION ---
    gmail_user = "rajcybertech08@gmail.com"
    app_password = "vjwu zzby igiz ufgm" # 16-character App Password
    # ---------------------

    # Create the email message
    msg = MIMEMultipart()
    msg['From'] = gmail_user
    msg['To'] = to_email
    msg['Subject'] = subject

    # Attach the body text
    msg.attach(MIMEText(body, 'plain'))

    server = None
    try:
        # SMTP Server setup for Gmail
        host = 'smtp.gmail.com'
        port = 587
        
        print(f"Connecting to {host}:{port}...")
        server = smtplib.SMTP(host, port)
        
        # Start encrypted TLS connection
        server.starttls()
        
        # Login to the account
        print(f"Logging in as {gmail_user}...")
        server.login(gmail_user, app_password)
        
        # Send the email
        text = msg.as_string()
        server.sendmail(gmail_user, to_email, text)
        
        print(f"✅ Success: Email sent to {to_email}")
        
    except smtplib.SMTPAuthenticationError:
        print("❌ Error: Authentication failed. Please check your Gmail address and App Password.")
        print("Ensure '2-Step Verification' is ON and you are using an 'App Password'.")
    except smtplib.SMTPConnectError:
        print("❌ Error: Could not connect to the SMTP server. Check your internet connection.")
    except Exception as e:
        print(f"❌ An unexpected error occurred: {e}")
    finally:
        # Securely close the connection
        if server:
            try:
                server.quit()
            except Exception:
                pass

if __name__ == "__main__":
    import sys
    import os
    from app import create_app, mongo
    
    # Initialize app to get database access
    app = create_app()
    
    # Default fallback recipient
    RECIPIENT = "none"
    
    # [1] Try to get recipient from Command Line first
    if len(sys.argv) > 1:
        RECIPIENT = sys.argv[1]
        print(f"Using command-line recipient: {RECIPIENT}")
    else:
        # [2] Automatically take from "Forgot Password" database
        with app.app_context():
            try:
                # Find the most recent reset request
                last_reset = mongo.db.password_resets.find_one(
                    sort=[("created_at", -1)]
                )
                
                if last_reset and last_reset.get('email'):
                    RECIPIENT = last_reset.get('email')
                    print(f"✅ Automatically found latest reset request for: {RECIPIENT}")
                else:
                    print(f"ℹ️ No recent reset found in DB. Using default: {RECIPIENT}")
            except Exception as db_err:
                print(f"⚠️ Database connection failed: {db_err}. Using default: {RECIPIENT}")

    # Build a professional message
    subject = "Reset Your Password - EDU Link Hub"
    body = f"""
Hello,

You requested to reset your password for your EDU Link Hub account. 
Please click the link below to set a new password:

http://127.0.0.1:5000/reset-password?token=LATEST_FORGOT_PASSWORD_TOKEN

If you did not request this, please ignore this email.

Best regards,
The EDU Link Hub Team
"""

    send_notification(
        subject=subject,
        body=body,
        to_email=RECIPIENT
    )
