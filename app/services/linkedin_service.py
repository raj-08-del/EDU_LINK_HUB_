import os
import requests
import logging

def get_linkedin_auth_url():
    """Generates the LinkedIn OAuth2 authorization URL."""
    client_id = os.getenv('LINKEDIN_CLIENT_ID')
    redirect_uri = os.getenv('LINKEDIN_REDIRECT_URI', 'http://127.0.0.1:5000/api/social/linkedin/callback')
    
    if not client_id:
        return None
        
    url = (
        f"https://www.linkedin.com/oauth/v2/authorization"
        f"?response_type=code"
        f"&client_id={client_id}"
        f"&redirect_uri={redirect_uri}"
        f"&state=edulinkhub_auth"
        f"&scope=openid%20profile%20email"
    )
    return url

def get_linkedin_token(code):
    """Exchanges the authorization code for an access token."""
    client_id = os.getenv('LINKEDIN_CLIENT_ID')
    client_secret = os.getenv('LINKEDIN_CLIENT_SECRET')
    redirect_uri = os.getenv('LINKEDIN_REDIRECT_URI', 'http://127.0.0.1:5000/api/social/linkedin/callback')
    
    url = "https://www.linkedin.com/oauth/v2/accessToken"
    data = {
        'grant_type': 'authorization_code',
        'code': code,
        'client_id': client_id,
        'client_secret': client_secret,
        'redirect_uri': redirect_uri
    }
    headers = {
        'Content-Type': 'application/x-www-form-urlencoded'
    }
    
    try:
        res = requests.post(url, data=data, headers=headers, timeout=10)
        res.raise_for_status()
        return res.json().get('access_token')
    except Exception as e:
        logging.error(f"Error fetching LinkedIn token: {e}")
        return None

def fetch_linkedin_profile(access_token):
    """Fetches user profile information using the access token."""
    url = "https://api.linkedin.com/v2/userinfo"
    headers = {
        'Authorization': f'Bearer {access_token}'
    }
    try:
        res = requests.get(url, headers=headers, timeout=10)
        res.raise_for_status()
        data = res.json()
        return {
            'name': data.get('name'),
            'given_name': data.get('given_name'),
            'family_name': data.get('family_name'),
            'picture': data.get('picture'),
            'email': data.get('email')
        }
    except Exception as e:
        logging.error(f"Error fetching LinkedIn profile: {e}")
        return None
