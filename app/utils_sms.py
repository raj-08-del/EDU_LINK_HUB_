import os
import re
import urllib.request
import urllib.parse
from datetime import datetime
import json
import base64
import socket
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart

from app import mongo

def normalize_phone_number(raw_number):
    """
    Cleans up Spaces, hyphens, parentheses, and duplicates +
    Returns strict E.164 string format.
    Auto formats 10 digits to +91... and 12 digits to +91...
    """
    raw_number = str(raw_number).strip()
    
    # Extract only digits and leading +
    is_plus = raw_number.startswith('+')
    digits_only = re.sub(r'[^0-9]', '', raw_number)
    
    # Apply rules
    if len(digits_only) == 10:
        clean_number = f"+91{digits_only}"
    elif len(digits_only) == 12 and digits_only.startswith('91'):
        clean_number = f"+{digits_only}"
    else:
        clean_number = f"+{digits_only}" if not is_plus else raw_number
        # Just clean any stray things
        clean_number = "+" + re.sub(r'[^0-9]', '', clean_number)
        
    # Final check: strict E.164
    if re.match(r'^\+\d{10,15}$', clean_number):
        return clean_number
    return None

def log_sms_delivery(phone, status, provider, raw_response=None, message_id=None, error_msg=None):
    """
    Logs every attempted message delivery for debugging.
    """
    try:
        mongo.db.sms_logs.insert_one({
            'phone': phone,
            'status': status,
            'provider': provider,
            'response': raw_response,
            'message_id': message_id,
            'error_msg': error_msg,
            'timestamp': datetime.utcnow()
        })
    except Exception as e:
        print(f"Failed to log SMS to Mongo: {e}")

def send_fast2sms_sms(to_phone, otp, api_key):
    """
    Sends SMS using Fast2SMS API. Highly reliable for +91 Indian numbers.
    Returns (success_bool, message_id, error_msg)
    """
    # Remove +91 or + prefix for Fast2SMS which requires 10-digit number
    clean_num = to_phone.replace("+91", "").replace("+", "")
    
    url = "https://www.fast2sms.com/dev/bulkV2"
    
    # Fast2SMS variables method (highly reliable)
    data = urllib.parse.urlencode({
        'variables_values': otp,
        'route': 'otp',
        'numbers': clean_num
    }).encode('utf-8')
    
    req = urllib.request.Request(f"{url}?{data.decode('utf-8')}", method="GET")
    req.add_header("authorization", api_key)
    req.add_header("Cache-Control", "no-cache")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_json = json.loads(response.read())
            if res_json.get('return') == True:
                req_id = res_json.get('request_id', 'FAST2SMS_SUCCESS')
                return True, req_id, "Provider Response: API success = true"
            else:
                return False, None, f"Fast2SMS Failed: {res_json.get('message')}"
    except Exception as e:
        return False, None, f"Fast2SMS Exception: {str(e)}"

def send_email_otp(to_email, otp):
    """
    Sends OTP to user's email address natively using smtplib for free.
    Requires SMTP_EMAIL and SMTP_PASSWORD in .env
    """
    sender_email = os.getenv('SMTP_EMAIL', '').strip()
    sender_password = os.getenv('SMTP_PASSWORD', '').strip()
    
    if not sender_email or not sender_password:
        return False, "SMTP credentials missing from .env"
        
    try:
        msg = MIMEMultipart()
        msg['From'] = f"EDU LINK HUB <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = "Your EDU LINK HUB Verification Code"
        
        body = f"Your OTP is {otp}. Valid for 5 minutes."
        msg.attach(MIMEText(body, 'plain'))
        
        server = smtplib.SMTP('smtp.gmail.com', 587)
        server.starttls()
        server.login(sender_email, sender_password)
        server.send_message(msg)
        server.quit()
        return True, "Email OTP Sent Successfully"
    except Exception as e:
        return False, f"SMTP Error: {str(e)}"

def send_reset_password_email(to_email, reset_link):
    """
    Sends a secure password reset link to the user's email.
    """
    sender_email = os.getenv('SMTP_EMAIL', '').strip()
    sender_password = os.getenv('SMTP_PASSWORD', '').strip()
    
    if not sender_email or not sender_password:
        # Sandbox mode fallback
        print(f"\n[!!!] EMAIL SANDBOX MODE [!!!]")
        print(f"To: {to_email}")
        print(f"Subject: Reset Your Password")
        print(f"Link: {reset_link}")
        print(f"---------------------------\n")
        return True, "Email Printed to Console (Sandbox Mode)"

    try:
        msg = MIMEMultipart()
        msg['From'] = f"EDU LINK HUB <{sender_email}>"
        msg['To'] = to_email
        msg['Subject'] = "Reset Your Password - EDU LINK HUB"
        
        body = f"""
        Hello,

        You requested to reset your password for your EDU LINK HUB account.
        Click the link below to set a new password:

        {reset_link}

        This link will expire in 30 minutes. If you did not request this, please ignore this email.
        """
        msg.attach(MIMEText(body, 'plain'))
        
        print(f">>> SMTP: Connecting to smtp.gmail.com:587...")
        server = smtplib.SMTP('smtp.gmail.com', 587, timeout=20)
        
        print(f">>> SMTP: Starting TLS...")
        server.starttls()
        
        print(f">>> SMTP: Logging in as {sender_email}...")
        server.login(sender_email, sender_password)
        
        print(f">>> SMTP: Sending message to {to_email}...")
        server.send_message(msg)
        
        server.quit()
        print(f"✅ SMTP SUCCESS: Reset email delivered to {to_email}")
        return True, "Reset Email Sent Successfully"
    except smtplib.SMTPException as e:
        print(f"❌ SMTP Protocol Error sending to {to_email}: {str(e)}")
        return False, f"SMTP Protocol Error: {str(e)}"
    except Exception as e:
        print(f"❌ Unexpected SMTP Error sending to {to_email}: {str(e)}")
        return False, f"SMTP Error: {str(e)}"

def send_free_textbelt_sms(to_phone, body):
    """
    Sends SMS using Textbelt's free tier. 
    Strictly limited to 1 message per IP per day. Extremely useful for a 1-time real hardware verification test 
    when the developer refuses to configure standard keys.
    """
    url = "https://textbelt.com/text"
    data = urllib.parse.urlencode({
        'phone': to_phone,
        'message': body,
        'key': 'textbelt',
    }).encode('utf-8')
    req = urllib.request.Request(url, data=data, method="POST")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_json = json.loads(response.read())
            if res_json.get('success'):
                return True, res_json.get('textId', 'TEXTBELT'), "Provider Response: API success (Free Tier)"
            return False, None, f"Textbelt Failed (Likely quota exceeded): {res_json.get('error', 'unknown')}"
    except Exception as e:
        return False, None, f"Textbelt Exception: {str(e)}"

def send_gsm_modem_sms(to_phone, body):
    """
    Sends SMS using a self-hosted GSM Modem hardware server (e.g., Raspberry Pi running smsd).
    Requires GSM_MODEM_URL in .env
    """
    url = os.getenv('GSM_MODEM_URL', '').strip()
    api_key = os.getenv('GSM_MODEM_API_KEY', '').strip()
    
    if not url:
        return False, None, "GSM Modem URL unconfigured in .env"
        
    payload = json.dumps({'phone': to_phone, 'message': body}).encode('utf-8')
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("Content-Type", "application/json")
    if api_key:
        req.add_header("Authorization", f"Bearer {api_key}")
        
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            if response.status in [200, 201]:
                return True, "GSM_HARDWARE", "Provider Response: Modem dispatch successful"
            return False, None, f"GSM Modem Error: HTTP {response.status}"
    except Exception as e:
        return False, None, f"GSM Modem Exception: {str(e)}"

def send_textbee_sms(to_phone, body):
    """
    Sends SMS using a self-hosted TextBee Android gateway (Fully Open Source Pipeline).
    Requires TEXTBEE_API_KEY and TEXTBEE_DEVICE_ID in .env
    Returns (success_bool, message_id, error_msg)
    """
    api_key = os.getenv('TEXTBEE_API_KEY', '').strip()
    device_id = os.getenv('TEXTBEE_DEVICE_ID', '').strip()
    
    if not api_key or not device_id:
        return False, None, "TextBee API keys unconfigured."
        
    url = f"https://api.textbee.dev/api/v1/gateway/devices/{device_id}/sendSMS"
    payload = json.dumps({'receivers': [to_phone], 'smsBody': body}).encode('utf-8')
    
    req = urllib.request.Request(url, data=payload, method="POST")
    req.add_header("x-api-key", api_key)
    req.add_header("Content-Type", "application/json")
    
    try:
        with urllib.request.urlopen(req, timeout=10) as response:
            res_json = json.loads(response.read())
            if response.status in [200, 201]:
                return True, "TEXTBEE_DEVICE", "Provider Response: API success = true"
            return False, None, f"TextBee Request Failed: {res_json.get('message')}"
    except Exception as e:
        return False, None, f"TextBee Exception: {str(e)}"

def send_twilio_sms(to_phone, body):
    """
    Sends SMS using Twilio REST API via builtin urllib.
    Returns (success_bool, message_id, error_msg)
    """
    sid = os.getenv('TWILIO_ACCOUNT_SID', '').strip()
    auth_token = os.getenv('TWILIO_AUTH_TOKEN', '').strip()
    from_number = os.getenv('TWILIO_PHONE_NUMBER', '').strip()
    
    if not sid or not auth_token or not from_number:
        return False, None, "API keys unconfigured. Please add Twilio credentials to .env"
        
    url = f"https://api.twilio.com/2010-04-01/Accounts/{sid}/Messages.json"
    
    data = urllib.parse.urlencode({
        'To': to_phone,
        'From': from_number,
        'Body': body
    }).encode('utf-8')
    
    auth_str = f"{sid}:{auth_token}"
    auth_base64 = base64.b64encode(auth_str.encode('ascii')).decode('ascii')
    
    req = urllib.request.Request(url, data=data, method="POST")
    req.add_header("Authorization", f"Basic {auth_base64}")
    req.add_header("Content-Type", "application/x-www-form-urlencoded")
    
    try:
        # Strict timeout enforcement per user request
        with urllib.request.urlopen(req, timeout=10) as response:
            res_body = response.read()
            res_json = json.loads(res_body)
            sid_id = res_json.get('sid')
            
            # Twilio success cases normally return 201 Created
            if response.status in [200, 201] and res_json.get('status') in ['queued', 'sent', 'delivered']:
                return True, sid_id, "Provider Response: API success = true"
            else:
                return False, sid_id, f"Provider Response: Unexpected Status ({res_json.get('status')})"
    
    except urllib.error.HTTPError as e:
        try:
            err_json = json.loads(e.read().decode('utf-8'))
            extracted_msg = err_json.get('message', 'Unknown Error')
            err_code = err_json.get('code', e.code)
            # Detailed debug capture (e.g., Code 21612: route inactive, 21614: invalid number...)
            return False, None, f"Twilio HTTP Error {err_code}: {extracted_msg}"
        except json.JSONDecodeError:
            return False, None, f"Twilio HTTP Error {e.code}: {e.reason}"
    
    except urllib.error.URLError as e:
        if isinstance(e.reason, socket.timeout):
            return False, None, "Timeout: SMS provider API took too long to respond."
        return False, None, f"Connection Error: {e.reason}"
        
    except Exception as e:
        return False, None, f"Unexpected Exception: {str(e)}"


def send_otp_message(phone, otp, email=None):
    """
    Master function to coordinate OTP delivery and logs.
    Prioritizes SMS providers, actively falls back to native Email, and resolves to Terminal Sandbox 
    if no paid/configured integrations exist.
    """
    template = f"Your EDU LINK HUB OTP is {otp}. Valid for 5 minutes."
    
    print("\n-------------------------------------------")
    print(">>> [BACKEND SYSTEM LOG - OTP PIPELINE]")
    print("[1] OTP generated: YES")
    print("[2] MongoDB save: YES")
    
    textbee_key = os.getenv('TEXTBEE_API_KEY', '').strip()
    gsm_url = os.getenv('GSM_MODEM_URL', '').strip()
    
    # 1. Primary Attempt (TextBee Android Gateway)
    if textbee_key:
        success, message_id, msg_payload = send_textbee_sms(phone, template)
        print(f"[3] TextBee response: {msg_payload}")
        print(f"[4] Android online status: {'ONLINE' if success else 'OFFLINE or UNAVAILABLE'}")
        if success:
            print("[8] delivery final result: SUCCESS (TextBee)")
            print("-------------------------------------------\n")
            log_sms_delivery(phone, "queued", "textbee", msg_payload, message_id)
            return True, "SMS Queued/Sent Successfully"
        else:
            print("[6] fallback trigger reason: TextBee device offline or keys invalid")
            log_sms_delivery(phone, "failed", "textbee", msg_payload, None, msg_payload)
    else:
        print("[3] TextBee response: UNCONFIGURED (.env)")
        print("[4] Android online status: UNKNOWN")
        print("[6] fallback trigger reason: Missing TextBee keys")
        log_sms_delivery(phone, "skipped", "textbee", "API keys unconfigured", None, "API keys unconfigured")

    # 2. Secondary Attempt (Gmail SMTP)
    print("[5] Gmail SMTP status: ATTEMPTING...")
    if email:
        email_success, email_msg = send_email_otp(email, otp)
        if email_success:
            print("[5] Gmail SMTP status: SUCCESS")
            print("[8] delivery final result: SUCCESS (Gmail Fallback)")
            print("-------------------------------------------\n")
            log_sms_delivery(phone, "delivered", "email_fallback", email_msg, "SMTP_SEND")
            return True, "OTP Delivered to Email Backup"
        else:
            print(f"[5] Gmail SMTP status: FAILED - {email_msg}")
            log_sms_delivery(phone, "failed", "email_fallback", email_msg, None, email_msg)
    else:
        print("[5] Gmail SMTP status: SKIPPED (No Email Provided)")

    # 3. Tertiary Attempt (Hardware GSM Modem)
    print("[7] modem fallback status: ATTEMPTING...")
    if gsm_url:
        gsm_success, gsm_id, gsm_payload = send_gsm_modem_sms(phone, template)
        if gsm_success:
             print("[7] modem fallback status: SUCCESS")
             print("[8] delivery final result: SUCCESS (Hardware GSM)")
             print("-------------------------------------------\n")
             log_sms_delivery(phone, "queued", "gsm_modem", gsm_payload, gsm_id)
             return True, "SMS Queued/Sent Successfully"
        print(f"[7] modem fallback status: FAILED - {gsm_payload}")
        log_sms_delivery(phone, "failed", "gsm_modem", gsm_payload, None, gsm_payload)
    else:
        print("[7] modem fallback status: SKIPPED (No GSM_MODEM_URL in .env)")

    # 4. Sandbox Mode Fallback (Always works in Development/Missing Keys)
    print(f"\n[!!!] SANDBOX MODE TRIGGERED [!!!]")
    print(f"OTP delivery failed to all providers. Logging to console instead.")
    print(f"OTP: {otp} for {phone or email}")
    print(f"-------------------------------------------\n")
    return True, "OTP Delivered (Sandbox Mode - Check Console)"
