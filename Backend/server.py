#!/usr/bin/env python3
"""
complete_server.py - Complete Hiring Bot Server
Combines: Chat Bot + All API Endpoints + Resume Management + Cloudflare Tunnel + AI Resume Filtering + User Authentication
"""

from flask import Flask, jsonify, request, send_file, render_template_string
from flask_cors import CORS
from flask_socketio import SocketIO, emit
import mysql.connector
from mysql.connector import Error
from datetime import datetime
import json
from functools import wraps
import logging
import re
import subprocess
import threading
import time
import os
import signal
import sys
import shutil
from werkzeug.utils import secure_filename
import base64
from pathlib import Path
import uuid
import socket
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.mime.base import MIMEBase
from email import encoders
import ssl
from threading import Thread
import hashlib
import secrets
try:
    import jwt
except ImportError:
    try:
        import PyJWT as jwt
    except ImportError:
        print("❌ PyJWT is not installed. Please run: pip install PyJWT")
        exit(1)
from datetime import datetime, timedelta

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import random
import string
import io
from datetime import datetime, timedelta

# Import AI bot handler
from ai_bot3 import ChatBotHandler, Config

# ============================================
# CONFIGURATION - HARDCODED
# ============================================
EMAIL_CONFIG = {
    # Option 1: Gmail SMTP (Recommended for testing)
    'SMTP_SERVER': 'smtp.gmail.com',
    'SMTP_PORT': 587,
    'EMAIL_ADDRESS': 'fardeen78754@gmail.com',  # Replace with your Gmail
    'EMAIL_PASSWORD': 'qfadfftaihyrfysu',
    'USE_TLS': True,
    'FROM_NAME': 'HR Team - Your Company',
    'COMPANY_NAME': 'Your Company Name',
    'COMPANY_WEBSITE': 'https://yourcompany.com',
    'HR_EMAIL': 'ffkhan@mitaoe.ac.in',
    'SEND_EMAILS': True  # Set to False to disable email sending

}

# TEXT CAPTCHA CONFIGURATION
CAPTCHA_LENGTH = 6  # Number of characters
CAPTCHA_TIMEOUT = 300  # 5 minutes in seconds
CAPTCHA_FONT_SIZE = 36
CAPTCHA_IMAGE_WIDTH = 200
CAPTCHA_IMAGE_HEIGHT = 80
active_captchas = {}

# MySQL Database Configuration
MYSQL_CONFIG = {
    'host': Config.MYSQL_HOST,
    'user': Config.MYSQL_USER,
    'password': Config.MYSQL_PASSWORD,
    'database': Config.MYSQL_DATABASE,
}

# API Configuration
API_KEY = "sk-hiring-bot-2024-secret-key-xyz789"  # Your secret API key
API_PORT = 5000  # Port number for the server

# JWT Configuration
JWT_SECRET_KEY = "your-jwt-secret-key-change-this-in-production"
JWT_ALGORITHM = "HS256"
JWT_EXPIRATION_HOURS = 24

# Cloudflare Tunnel Configuration
CLOUDFLARE_TUNNEL_NAME = "hiring-bot-complete"  # Name for your tunnel
CLOUDFLARE_TUNNEL_URL = None  # Will be set after tunnel starts

# File Storage Configuration
BASE_STORAGE_PATH = "approved_tickets"  # Base folder for storing approved tickets
ALLOWED_EXTENSIONS = {'pdf', 'doc', 'docx', 'txt', 'rtf'}
MAX_FILE_SIZE = 10 * 1024 * 1024  # 10MB max file size

# ============================================
# Flask App Initialization
# ============================================

# Initialize Flask app
app = Flask(__name__)
app.config['SECRET_KEY'] = 'your-secret-key-change-this-in-production'
app.config['MAX_CONTENT_LENGTH'] = MAX_FILE_SIZE
CORS(app, origins="*")  # Configure appropriately for production

# Initialize SocketIO for real-time chat
socketio = SocketIO(app, cors_allowed_origins="*")

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Create base storage directory if it doesn't exist
if not os.path.exists(BASE_STORAGE_PATH):
    os.makedirs(BASE_STORAGE_PATH)
    logger.info(f"Created base storage directory: {BASE_STORAGE_PATH}")

# Initialize chat bot handler
chat_bot = ChatBotHandler()
logger.info("Chat bot handler initialized successfully")

# ============================================
# Database Helper Functions
# ============================================

def get_db_connection():
    """Create and return database connection"""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except Error as e:
        logger.error(f"Database connection failed: {e}")
        return None

def serialize_datetime(obj):
    """Convert datetime objects to ISO format strings"""
    if isinstance(obj, datetime):
        return obj.isoformat()
    return obj

# ============================================
# Authentication Decorator
# ============================================

def require_api_key(f):
    """Decorator to require API key for endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        api_key = request.headers.get('X-API-Key')
        
        # Also check URL parameter as fallback
        if not api_key:
            api_key = request.args.get('api_key')
        
        if api_key != API_KEY:
            return jsonify({
                'success': False,
                'error': 'Invalid or missing API key'
            }), 401
        
        return f(*args, **kwargs)
    return decorated_function

def require_jwt_auth(f):
    """Decorator to require JWT authentication for HR endpoints"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'error': 'Authorization header required'
            }), 401
        
        token = auth_header.split(' ')[1]
        
        # Verify token
        is_valid, payload = verify_jwt_token(token)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': payload
            }), 401
        
        # Check if user is HR manager
        if payload.get('role') != 'hr':
            return jsonify({
                'success': False,
                'error': 'Access denied. Only HR managers can access this endpoint.'
            }), 403
        
        # Add user info to request context
        request.user = payload
        
        return f(*args, **kwargs)
    return decorated_function

# ============================================
# Cloudflare Tunnel Functions
# ============================================

def get_thank_you_email_template(candidate_name, job_title, application_id, company_name):
    """Generate HTML email template for thank you message"""
    
    html_template = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <meta name="viewport" content="width=device-width, initial-scale=1.0">
        <title>Application Received - {company_name}</title>
        <style>
            body {{ font-family: Arial, sans-serif; line-height: 1.6; color: #333; margin: 0; padding: 0; }}
            .container {{ max-width: 600px; margin: 0 auto; padding: 20px; }}
            .header {{ background: linear-gradient(135deg, #667eea 0%, #764ba2 100%); color: white; padding: 30px; text-align: center; border-radius: 10px 10px 0 0; }}
            .content {{ background: #f9f9f9; padding: 30px; border-radius: 0 0 10px 10px; }}
            .highlight {{ background: #e3f2fd; padding: 15px; border-radius: 5px; margin: 20px 0; border-left: 4px solid #2196f3; }}
            .footer {{ text-align: center; margin-top: 30px; padding: 20px; color: #666; font-size: 14px; }}
            .button {{ display: inline-block; background: #4CAF50; color: white; padding: 12px 24px; text-decoration: none; border-radius: 5px; margin: 10px 0; }}
            .details {{ background: white; padding: 20px; border-radius: 5px; margin: 20px 0; border: 1px solid #ddd; }}
            .status {{ background: #4CAF50; color: white; padding: 8px 16px; border-radius: 20px; font-size: 12px; font-weight: bold; }}
        </style>
    </head>
    <body>
        <div class="container">
            <div class="header">
                <h1>🎉 Application Received!</h1>
                <p>Thank you for your interest in joining our team</p>
            </div>
            
            <div class="content">
                <h2>Dear {candidate_name},</h2>
                
                <p>Thank you for submitting your application for the <strong>{job_title}</strong> position. We have successfully received your resume and application materials.</p>
                
                <div class="highlight">
                    <h3>📋 Application Details</h3>
                    <div class="details">
                        <p><strong>Position:</strong> {job_title}</p>
                        <p><strong>Application ID:</strong> {application_id}</p>
                        <p><strong>Submitted:</strong> {datetime.now().strftime('%B %d, %Y at %I:%M %p')}</p>
                        <p><strong>Status:</strong> <span class="status">RECEIVED</span></p>
                    </div>
                </div>
                
                <h3>🔄 What happens next?</h3>
                <ul>
                    <li><strong>Review Process:</strong> Our HR team will carefully review your application and resume</li>
                    <li><strong>AI Screening:</strong> Your application will go through our advanced AI screening process to match your skills with job requirements</li>
                    <li><strong>Initial Assessment:</strong> If your profile matches our requirements, we'll contact you within 5-7 business days</li>
                    <li><strong>Interview Process:</strong> Qualified candidates will be invited for interviews</li>
                </ul>
                
                <div class="highlight">
                    <h3>📞 Need Help?</h3>
                    <p>If you have any questions about your application or the hiring process, please don't hesitate to contact us:</p>
                    <p><strong>Email:</strong> {EMAIL_CONFIG['HR_EMAIL']}</p>
                    <p><strong>Application ID:</strong> {application_id} (Please reference this in any communication)</p>
                </div>
                
                <p><strong>Important:</strong> Please keep this email for your records. The Application ID will help us track your application status.</p>
                
                <p>We appreciate your interest in {company_name} and look forward to potentially working with you!</p>
                
                <p>Best regards,<br>
                <strong>The HR Team</strong><br>
                {company_name}</p>
            </div>
            
            <div class="footer">
                <p>This is an automated message. Please do not reply to this email.</p>
                <p>Visit our website: <a href="{EMAIL_CONFIG['COMPANY_WEBSITE']}">{EMAIL_CONFIG['COMPANY_WEBSITE']}</a></p>
                <p>&copy; 2025 {company_name}. All rights reserved.</p>
            </div>
        </div>
    </body>
    </html>
    """
    
    # Plain text version for email clients that don't support HTML
    text_template = f"""
    Dear {candidate_name},

    Thank you for submitting your application for the {job_title} position!

    APPLICATION DETAILS:
    - Position: {job_title}
    - Application ID: {application_id}
    - Submitted: {datetime.now().strftime('%B %d, %Y at %I:%M %p')}
    - Status: RECEIVED

    WHAT HAPPENS NEXT:
    1. Our HR team will review your application
    2. AI screening will match your skills with job requirements
    3. We'll contact qualified candidates within 5-7 business days
    4. Interview process for selected candidates

    NEED HELP?
    Email: {EMAIL_CONFIG['HR_EMAIL']}
    Reference: Application ID {application_id}

    Best regards,
    The HR Team
    {company_name}

    This is an automated message. Please do not reply.
    """
    
    return html_template, text_template

def send_email(to_email, subject, html_content, text_content, from_name=None):
    """Send email using SMTP"""
    if not EMAIL_CONFIG.get('SEND_EMAILS', True):
        logger.info(f"Email sending disabled. Would send to: {to_email}")
        return True, "Email sending disabled"
    
    try:
        # Create message
        message = MIMEMultipart("alternative")
        message["Subject"] = subject
        message["From"] = f"{from_name or EMAIL_CONFIG['FROM_NAME']} <{EMAIL_CONFIG['EMAIL_ADDRESS']}>"
        message["To"] = to_email
        
        # Add both text and HTML parts
        text_part = MIMEText(text_content, "plain")
        html_part = MIMEText(html_content, "html")
        
        message.attach(text_part)
        message.attach(html_part)
        
        # Create SMTP session
        server = smtplib.SMTP(EMAIL_CONFIG['SMTP_SERVER'], EMAIL_CONFIG['SMTP_PORT'])
        
        if EMAIL_CONFIG.get('USE_TLS', True):
            server.starttls()  # Enable TLS encryption
        
        # Login and send email
        server.login(EMAIL_CONFIG['EMAIL_ADDRESS'], EMAIL_CONFIG['EMAIL_PASSWORD'])
        server.sendmail(EMAIL_CONFIG['EMAIL_ADDRESS'], to_email, message.as_string())
        server.quit()
        
        logger.info(f"Email sent successfully to {to_email}")
        return True, "Email sent successfully"
        
    except Exception as e:
        logger.error(f"Failed to send email to {to_email}: {str(e)}")
        return False, str(e)

def send_thank_you_email_async(candidate_email, candidate_name, job_title, application_id):
    """Send thank you email in background thread"""
    def send_email_task():
        try:
            # Generate email content
            html_content, text_content = get_thank_you_email_template(
                candidate_name, 
                job_title, 
                application_id, 
                EMAIL_CONFIG['COMPANY_NAME']
            )
            
            # Send email
            subject = f"Application Received - {job_title} Position | {EMAIL_CONFIG['COMPANY_NAME']}"
            
            success, message = send_email(
                candidate_email,
                subject,
                html_content,
                text_content,
                EMAIL_CONFIG['FROM_NAME']
            )
            
            if success:
                logger.info(f"Thank you email sent to {candidate_name} ({candidate_email}) for application {application_id}")
            else:
                logger.error(f"Failed to send thank you email to {candidate_name}: {message}")
                
        except Exception as e:
            logger.error(f"Error in email sending task: {str(e)}")
    
    # Run in background thread
    email_thread = Thread(target=send_email_task, daemon=True)
    email_thread.start()


def check_cloudflared_installed():
    """Check if cloudflared is installed"""
    try:
        result = subprocess.run(['cloudflared', 'version'], 
                              capture_output=True, text=True)
        return result.returncode == 0
    except FileNotFoundError:
        return False

def install_cloudflared():
    """Install cloudflared if not present"""
    print("\n" + "="*60)
    print("📦 Installing Cloudflare Tunnel (cloudflared)...")
    print("="*60)
    
    system = sys.platform
    
    try:
        if system == "linux" or system == "linux2":
            # Linux installation
            commands = [
                "wget -q https://github.com/cloudflare/cloudflared/releases/latest/download/cloudflared-linux-amd64.deb",
                "sudo dpkg -i cloudflared-linux-amd64.deb",
                "rm cloudflared-linux-amd64.deb"
            ]
            for cmd in commands:
                subprocess.run(cmd, shell=True, check=True)
                
        elif system == "darwin":
            # macOS installation
            subprocess.run("brew install cloudflare/cloudflare/cloudflared", 
                         shell=True, check=True)
                         
        elif system == "win32":
            # Windows installation
            print("Please download cloudflared from:")
            print("https://github.com/cloudflare/cloudflared/releases")
            print("Add it to your PATH and restart the script.")
            return False
            
        print("✅ Cloudflared installed successfully!")
        return True
        
    except subprocess.CalledProcessError as e:
        print(f"❌ Failed to install cloudflared: {e}")
        print("\nPlease install manually:")
        print("https://developers.cloudflare.com/cloudflare-one/connections/connect-apps/install-and-setup/installation")
        return False

def start_cloudflare_tunnel():
    """Start Cloudflare tunnel and return public URL"""
    global CLOUDFLARE_TUNNEL_URL
    
    if not check_cloudflared_installed():
        if not install_cloudflared():
            return None
    
    print("\n" + "="*60)
    print("🌐 Starting Cloudflare Tunnel...")
    print("="*60)
    
    try:
        # Check if user is logged in
        login_check = subprocess.run(['cloudflared', 'tunnel', 'list'], 
                                   capture_output=True, text=True)
        
        if login_check.returncode != 0 or "You need to login" in login_check.stderr:
            print("📝 First time setup - Please login to Cloudflare")
            print("This will open your browser for authentication...")
            subprocess.run(['cloudflared', 'tunnel', 'login'])
            print("✅ Login successful!")
        
        # Try to create tunnel (will fail if exists, which is fine)
        create_result = subprocess.run(
            ['cloudflared', 'tunnel', 'create', CLOUDFLARE_TUNNEL_NAME],
            capture_output=True, text=True
        )
        
        if "already exists" in create_result.stderr:
            print(f"ℹ️  Tunnel '{CLOUDFLARE_TUNNEL_NAME}' already exists")
        elif create_result.returncode == 0:
            print(f"✅ Created tunnel '{CLOUDFLARE_TUNNEL_NAME}'")
        else:
            print(f"⚠️  Tunnel creation: {create_result.stderr}")
        
        # Start the tunnel with try.cloudflare.com for quick testing
        tunnel_process = subprocess.Popen(
            ['cloudflared', 'tunnel', '--url', f'http://localhost:{API_PORT}'],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True
        )
        
        # Wait for tunnel to establish and capture URL
        print("⏳ Establishing tunnel connection...")
        
        start_time = time.time()
        while time.time() - start_time < 30:  # 30 second timeout
            line = tunnel_process.stderr.readline()
            
            # Look for the public URL in the output
            if "https://" in line and ".trycloudflare.com" in line:
                # Extract URL from the line
                url_match = re.search(r'https://[^\s]+\.trycloudflare\.com', line)
                if url_match:
                    CLOUDFLARE_TUNNEL_URL = url_match.group(0)
                    break
        
        if CLOUDFLARE_TUNNEL_URL:
            print("\n" + "="*60)
            print("🎉 CLOUDFLARE TUNNEL ACTIVE")
            print("="*60)
            print(f"📱 Public URL: {CLOUDFLARE_TUNNEL_URL}")
            print(f"🔗 Share this URL to access your complete system from anywhere")
            print(f"🔐 API Key: {API_KEY}")
            print("="*60 + "\n")
            
            # Keep tunnel process running in background
            tunnel_thread = threading.Thread(
                target=monitor_tunnel_process, 
                args=(tunnel_process,),
                daemon=True
            )
            tunnel_thread.start()
            
            return CLOUDFLARE_TUNNEL_URL
        else:
            print("❌ Failed to establish tunnel - timeout")
            tunnel_process.terminate()
            return None
            
    except Exception as e:
        print(f"❌ Error starting tunnel: {e}")
        return None

def monitor_tunnel_process(process):
    """Monitor tunnel process and restart if needed"""
    while True:
        output = process.stderr.readline()
        if output:
            # Log tunnel output for debugging (optional)
            if "error" in output.lower():
                logger.error(f"Tunnel error: {output.strip()}")
        
        # Check if process is still running
        if process.poll() is not None:
            logger.error("Tunnel process died! Restarting...")
            # Could implement restart logic here
            break
        
        time.sleep(1)

def stop_cloudflare_tunnel():
    """Stop all cloudflared processes"""
    try:
        if sys.platform == "win32":
            subprocess.run("taskkill /F /IM cloudflared.exe", shell=True)
        else:
            subprocess.run("pkill cloudflared", shell=True)
        print("✅ Cloudflare tunnel stopped")
    except:
        pass

# ============================================
# File Storage Helper Functions
# ============================================

def allowed_file(filename):
    """Check if file extension is allowed"""
    return '.' in filename and \
           filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS

# ============================================
# ENHANCED FOLDER MANAGEMENT SYSTEM
# ============================================

def ensure_job_folder_exists(ticket_id, ticket_subject=None):
    """Ensure a job folder exists for a ticket, create if it doesn't"""
    try:
        # Check if folder already exists
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if ticket_folders:
            # Folder exists, return the path
            folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
            logger.info(f"Job folder already exists for ticket {ticket_id}: {folder_path}")
            return folder_path
        else:
            # Create new folder
            folder_path = create_ticket_folder(ticket_id, ticket_subject)
            if folder_path:
                logger.info(f"Created new job folder for ticket {ticket_id}: {folder_path}")
                return folder_path
            else:
                logger.error(f"Failed to create job folder for ticket {ticket_id}")
                return None
                
    except Exception as e:
        logger.error(f"Error ensuring job folder exists for ticket {ticket_id}: {e}")
        return None

def auto_create_folders_for_pending_tickets():
    """Automatically create folders for all pending tickets that should have folders"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to connect to database for auto folder creation")
            return
        
        cursor = conn.cursor(dictionary=True)
        
        # Get all tickets that should have folders (approved or have resumes)
        cursor.execute("""
            SELECT DISTINCT t.ticket_id, t.subject, t.approval_status
            FROM tickets t
            LEFT JOIN (
                SELECT ticket_id, COUNT(*) as resume_count
                FROM ticket_details 
                WHERE field_name = 'resume_uploaded' AND field_value = 'true'
                GROUP BY ticket_id
            ) r ON t.ticket_id = r.ticket_id
            WHERE t.approval_status = 'approved' 
               OR r.resume_count > 0
               OR t.status = 'active'
        """)
        
        tickets = cursor.fetchall()
        created_count = 0
        existing_count = 0
        
        logger.info(f"Checking {len(tickets)} tickets for folder creation...")
        
        for ticket in tickets:
            ticket_id = ticket['ticket_id']
            
            # Check if folder already exists
            ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                            if f.startswith(f"{ticket_id}_")]
            
            if ticket_folders:
                existing_count += 1
                logger.debug(f"Folder already exists for ticket {ticket_id}")
            else:
                # Create folder
                folder_path = create_ticket_folder(ticket_id, ticket['subject'])
                if folder_path:
                    created_count += 1
                    logger.info(f"Auto-created folder for ticket {ticket_id}: {os.path.basename(folder_path)}")
                else:
                    logger.error(f"Failed to auto-create folder for ticket {ticket_id}")
        
        cursor.close()
        conn.close()
        
        logger.info(f"Auto folder creation complete: {created_count} created, {existing_count} existing")
        
    except Exception as e:
        logger.error(f"Error in auto_create_folders_for_pending_tickets: {e}")

def get_job_folder_info(ticket_id):
    """Get comprehensive information about a job folder"""
    try:
        # Find the ticket folder
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            return {
                'exists': False,
                'folder_name': None,
                'folder_path': None,
                'resume_count': 0,
                'job_details': None,
                'metadata': None,
                'created_at': None
            }
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        
        # Get folder info
        folder_info = {
            'exists': True,
            'folder_name': ticket_folders[0],
            'folder_path': folder_path,
            'created_at': datetime.fromtimestamp(os.path.getctime(folder_path)).isoformat(),
            'resume_count': 0,
            'job_details': None,
            'metadata': None
        }
        
        # Get metadata
        metadata_path = os.path.join(folder_path, 'metadata.json')
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                folder_info['metadata'] = json.load(f)
                folder_info['resume_count'] = len(folder_info['metadata'].get('resumes', []))
        
        # Get job details
        job_details_path = os.path.join(folder_path, 'job_details.json')
        if os.path.exists(job_details_path):
            with open(job_details_path, 'r') as f:
                folder_info['job_details'] = json.load(f)
        
        # Count actual resume files
        resume_files = [f for f in os.listdir(folder_path) 
                       if f.lower().endswith(('.pdf', '.doc', '.docx', '.txt'))]
        folder_info['actual_resume_files'] = len(resume_files)
        
        return folder_info
        
    except Exception as e:
        logger.error(f"Error getting job folder info for ticket {ticket_id}: {e}")
        return {
            'exists': False,
            'error': str(e)
        }

def cleanup_orphaned_folders():
    """Remove folders that don't have corresponding tickets"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to connect to database for cleanup")
            return
        
        cursor = conn.cursor()
        
        # Get all valid ticket IDs
        cursor.execute("SELECT ticket_id FROM tickets")
        valid_ticket_ids = {row[0] for row in cursor.fetchall()}
        
        cursor.close()
        conn.close()
        
        # Check all folders
        orphaned_folders = []
        for folder_name in os.listdir(BASE_STORAGE_PATH):
            if folder_name.startswith('batch_results') or folder_name.startswith('.'):
                continue  # Skip special folders
                
            # Extract ticket ID from folder name
            ticket_id = folder_name.split('_')[0]
            
            if ticket_id not in valid_ticket_ids:
                orphaned_folders.append(folder_name)
        
        # Remove orphaned folders
        for folder_name in orphaned_folders:
            folder_path = os.path.join(BASE_STORAGE_PATH, folder_name)
            try:
                shutil.rmtree(folder_path)
                logger.info(f"Removed orphaned folder: {folder_name}")
            except Exception as e:
                logger.error(f"Failed to remove orphaned folder {folder_name}: {e}")
        
        logger.info(f"Cleanup complete: {len(orphaned_folders)} orphaned folders removed")
        
    except Exception as e:
        logger.error(f"Error in cleanup_orphaned_folders: {e}")

def create_ticket_folder(ticket_id, ticket_subject=None):
    """Create a folder for approved ticket"""
    try:
        # Clean ticket subject for folder name
        if ticket_subject:
            # Remove special characters and limit length
            clean_subject = re.sub(r'[^\w\s-]', '', ticket_subject)
            clean_subject = re.sub(r'[-\s]+', '-', clean_subject)
            clean_subject = clean_subject[:50].strip('-')
            folder_name = f"{ticket_id}_{clean_subject}"
        else:
            folder_name = str(ticket_id)
        
        folder_path = os.path.join(BASE_STORAGE_PATH, folder_name)
        
        if not os.path.exists(folder_path):
            os.makedirs(folder_path)
            logger.info(f"Created folder for ticket {ticket_id}: {folder_path}")
            
            # Create a metadata file
            metadata = {
                'ticket_id': ticket_id,
                'created_at': datetime.now().isoformat(),
                'folder_name': folder_name,
                'resumes': []
            }
            
            metadata_path = os.path.join(folder_path, 'metadata.json')
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
            
            # Also save job details
            save_job_details_to_folder(ticket_id, folder_path)
        
        return folder_path
        
    except Exception as e:
        logger.error(f"Error creating folder for ticket {ticket_id}: {e}")
        return None

def save_job_details_to_folder(ticket_id, folder_path):
    """Save job details to a JSON file in the ticket folder"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to connect to database for job details")
            return False
        
        cursor = conn.cursor(dictionary=True)
        
        # Get ticket information
        cursor.execute("""
            SELECT * FROM tickets 
            WHERE ticket_id = %s
        """, (ticket_id,))
        
        ticket = cursor.fetchone()
        if not ticket:
            cursor.close()
            conn.close()
            return False
        
        # Get the LATEST value for each field
        cursor.execute("""
            SELECT 
                td1.field_name,
                td1.field_value
            FROM ticket_details td1
            INNER JOIN (
                SELECT field_name, MAX(created_at) as max_created_at
                FROM ticket_details
                WHERE ticket_id = %s
                GROUP BY field_name
            ) td2 ON td1.field_name = td2.field_name 
                 AND td1.created_at = td2.max_created_at
            WHERE td1.ticket_id = %s
        """, (ticket_id, ticket_id))
        
        job_details = {}
        for row in cursor.fetchall():
            job_details[row['field_name']] = row['field_value']
        
        # Convert datetime objects to string
        for key, value in ticket.items():
            if isinstance(value, datetime):
                ticket[key] = value.isoformat()
        
        # Combine ticket info with job details
        complete_job_info = {
            'ticket_info': ticket,
            'job_details': job_details,
            'saved_at': datetime.now().isoformat()
        }
        
        # Save to job_details.json
        job_details_path = os.path.join(folder_path, 'job_details.json')
        with open(job_details_path, 'w', encoding='utf-8') as f:
            json.dump(complete_job_info, f, indent=2, ensure_ascii=False)
        
        logger.info(f"Saved job details for ticket {ticket_id}")
        
        cursor.close()
        conn.close()
        return True
        
    except Exception as e:
        logger.error(f"Error saving job details for ticket {ticket_id}: {e}")
        return False

def update_job_details_in_folder(ticket_id):
    """Update job details file when ticket information changes"""
    try:
        # Find the ticket folder
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            logger.error(f"No folder found for ticket {ticket_id}")
            return False
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        return save_job_details_to_folder(ticket_id, folder_path)
        
    except Exception as e:
        logger.error(f"Error updating job details for ticket {ticket_id}: {e}")
        return False

def save_resume_to_ticket(ticket_id, file, applicant_name=None, applicant_email=None):
    """Save resume to ticket folder"""
    try:
        # Get ticket folder path
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            logger.error(f"No folder found for ticket {ticket_id}")
            return None
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        
        # Generate unique filename
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        original_filename = secure_filename(file.filename)
        base_name, ext = os.path.splitext(original_filename)
        
        if applicant_name:
            clean_name = re.sub(r'[^\w\s-]', '', applicant_name)
            clean_name = re.sub(r'[-\s]+', '_', clean_name)
            filename = f"{clean_name}_{timestamp}{ext}"
        else:
            filename = f"resume_{timestamp}{ext}"
        
        file_path = os.path.join(folder_path, filename)
        
        # Save file
        file.save(file_path)
        
        # Update metadata
        metadata_path = os.path.join(folder_path, 'metadata.json')
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
            
            resume_info = {
                'filename': filename,
                'original_filename': original_filename,
                'uploaded_at': datetime.now().isoformat(),
                'applicant_name': applicant_name,
                'applicant_email': applicant_email,
                'file_size': os.path.getsize(file_path)
            }
            
            metadata['resumes'].append(resume_info)
            
            with open(metadata_path, 'w') as f:
                json.dump(metadata, f, indent=2)
        
        logger.info(f"Saved resume {filename} for ticket {ticket_id}")
        return file_path
        
    except Exception as e:
        logger.error(f"Error saving resume for ticket {ticket_id}: {e}")
        return None

def get_ticket_resumes(ticket_id):
    """Get list of resumes for a ticket"""
    try:
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            return []
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        metadata_path = os.path.join(folder_path, 'metadata.json')
        
        if os.path.exists(metadata_path):
            with open(metadata_path, 'r') as f:
                metadata = json.load(f)
                return metadata.get('resumes', [])
        
        return []
        
    except Exception as e:
        logger.error(f"Error getting resumes for ticket {ticket_id}: {e}")
        return []

def create_folders_for_existing_approved_tickets():
    """Create folders for all existing approved tickets"""
    try:
        conn = get_db_connection()
        if not conn:
            logger.error("Failed to connect to database")
            return
        
        cursor = conn.cursor(dictionary=True)
        
        # Get all approved tickets
        cursor.execute("""
            SELECT ticket_id, subject
            FROM tickets
            WHERE approval_status = 'approved'
        """)
        
        approved_tickets = cursor.fetchall()
        created_count = 0
        existing_count = 0
        
        print(f"\n📁 Checking {len(approved_tickets)} approved tickets for folders...")
        
        for ticket in approved_tickets:
            ticket_id = ticket['ticket_id']
            
            # Check if folder already exists
            ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                            if f.startswith(f"{ticket_id}_")]
            
            if ticket_folders:
                existing_count += 1
                print(f"   ✓ Folder already exists for ticket {ticket_id}")
                # Update job details in existing folder
                folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
                save_job_details_to_folder(ticket_id, folder_path)
                print(f"   📄 Updated job details for ticket {ticket_id}")
            else:
                # Create folder (which will also save job details)
                folder_path = create_ticket_folder(ticket_id, ticket['subject'])
                if folder_path:
                    created_count += 1
                    print(f"   ✅ Created folder for ticket {ticket_id}: {os.path.basename(folder_path)}")
                    print(f"   📄 Saved job details for ticket {ticket_id}")
                else:
                    print(f"   ❌ Failed to create folder for ticket {ticket_id}")
        
        cursor.close()
        conn.close()
        
        print(f"\n📊 Summary:")
        print(f"   - New folders created: {created_count}")
        print(f"   - Existing folders: {existing_count}")
        print(f"   - Total approved tickets: {len(approved_tickets)}")
        
    except Exception as e:
        logger.error(f"Error creating folders for existing tickets: {e}")
        print(f"❌ Error: {e}")

# ============================================
# CHAT INTERFACE AND ENDPOINTS
# ============================================

@app.route('/')
def index():
    """Serve the main interface with both chat and API info"""
    return render_template_string(r'''
    <!DOCTYPE html>
    <html>
    <head>
        <title>Hiring Bot - Complete System</title>
        <style>
            body { 
                font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
                max-width: 1200px; 
                margin: 0 auto; 
                padding: 20px;
                background-color: #f5f5f5;
            }
            .container {
                display: grid;
                grid-template-columns: 1fr 1fr;
                gap: 20px;
                margin-top: 20px;
            }
            .section {
                background: white;
                padding: 20px;
                border-radius: 8px;
                box-shadow: 0 2px 4px rgba(0,0,0,0.1);
            }
            .chat-section {
                grid-column: span 2;
            }
            h1, h2 { color: #333; }
            #chat-container { 
                border: 1px solid #ddd; 
                height: 400px; 
                overflow-y: auto; 
                padding: 15px; 
                margin-bottom: 10px;
                background: #fafafa;
                border-radius: 4px;
            }
            .message { 
                margin: 10px 0; 
                padding: 10px;
                border-radius: 8px;
                max-width: 70%;
            }
            .user { 
                background: #007bff;
                color: white;
                margin-left: auto;
                text-align: right;
            }
            .bot { 
                background: #e9ecef;
                color: #333;
            }
            #input-container { 
                display: flex; 
                gap: 10px;
            }
            #message-input { 
                flex: 1; 
                padding: 12px;
                border: 1px solid #ddd;
                border-radius: 4px;
                font-size: 14px;
            }
            #send-button { 
                padding: 12px 24px;
                background: #007bff;
                color: white;
                border: none;
                border-radius: 4px;
                cursor: pointer;
                font-size: 14px;
            }
            #send-button:hover {
                background: #0056b3;
            }
            .api-info {
                background: #f8f9fa;
                padding: 15px;
                border-radius: 4px;
                margin-top: 10px;
            }
            .api-info code {
                background: #e9ecef;
                padding: 2px 6px;
                border-radius: 3px;
                font-family: 'Courier New', monospace;
            }
            .status-indicator {
                display: inline-block;
                width: 10px;
                height: 10px;
                border-radius: 50%;
                margin-right: 5px;
            }
            .status-active { background: #28a745; }
            .status-inactive { background: #dc3545; }
            .endpoint-list {
                max-height: 300px;
                overflow-y: auto;
                font-size: 13px;
            }
        </style>
    </head>
    <body>
        <h1>🤖 Hiring Bot - Complete System</h1>
        
        <div class="container">
            <div class="section">
                <h2>📊 System Status</h2>
                <p><span class="status-indicator status-active"></span> Server: Active</p>
                <p><span class="status-indicator {% if tunnel_url %}status-active{% else %}status-inactive{% endif %}"></span> 
                   Cloudflare Tunnel: {% if tunnel_url %}Active{% else %}Local Only{% endif %}</p>
                <p>🔐 API Key: <code>{{ api_key[:20] }}...</code></p>
                {% if tunnel_url %}
                <p>🌐 Public URL: <code>{{ tunnel_url }}</code></p>
                {% endif %}
            </div>
            
            <div class="section">
                <h2>🔗 Quick Links</h2>
                <p>📚 <a href="/api/health">Health Check</a></p>
                <p>💼 <a href="/api/jobs/approved?api_key={{ api_key }}">View Approved Jobs</a></p>
                <p>📊 <a href="/api/stats?api_key={{ api_key }}">Statistics</a></p>
                <p>📍 <a href="/api/locations?api_key={{ api_key }}">Locations</a></p>
                <p>🛠️ <a href="/api/skills?api_key={{ api_key }}">Skills</a></p>
            </div>
        </div>
        
        <div class="section chat-section">
            <h2>💬 Chat with Hiring Bot</h2>
            <div id="chat-container"></div>
            <div id="input-container">
                <input type="text" id="message-input" placeholder="Type your message... (try 'I want to post a job' or 'help')" />
                <button id="send-button">Send</button>
            </div>
        </div>
        
        <div class="section api-info">
            <h3>API Endpoints</h3>
            <div class="endpoint-list">
                <p><strong>Chat Endpoints:</strong></p>
                <ul>
                    <li>POST /api/chat/start - Start new chat session</li>
                    <li>POST /api/chat/message - Send message</li>
                    <li>GET /api/chat/history/&lt;id&gt; - Get chat history</li>
                </ul>
                <p><strong>Job Management:</strong></p>
                <ul>
                    <li>GET /api/jobs/approved - Get approved jobs</li>
                    <li>GET /api/jobs/&lt;id&gt; - Get job details</li>
                    <li>GET /api/jobs/search?q=python - Search jobs</li>
                    <li>POST /api/tickets/&lt;id&gt;/approve - Approve ticket</li>
                </ul>
                <p><strong>Resume Management:</strong></p>
                <ul>
                    <li>POST /api/tickets/&lt;id&gt;/resumes - Upload resume</li>
                    <li>GET /api/tickets/&lt;id&gt;/resumes - List resumes</li>
                    <li>GET /api/tickets/&lt;id&gt;/resumes/&lt;filename&gt; - Download resume</li>
                </ul>
                <p><strong>Resume Filtering:</strong></p>
                <ul>
                    <li>POST /api/tickets/&lt;id&gt;/filter-resumes - Trigger filtering</li>
                    <li>GET /api/tickets/&lt;id&gt;/top-resumes - Get top candidates</li>
                    <li>GET /api/tickets/&lt;id&gt;/filtering-report - Get report</li>
                    <li>GET /api/tickets/&lt;id&gt;/filtering-status - Check status</li>
                    <li>POST /api/tickets/&lt;id&gt;/send-top-resumes - Send via webhook</li>
                </ul>
            </div>
        </div>
        
        <script>
            let sessionId = null;
            let userId = 'user_' + Math.random().toString(36).substr(2, 9);
            
            // Start chat session
            async function startChat() {
                const response = await fetch('/api/chat/start', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({user_id: userId})
                });
                const data = await response.json();
                sessionId = data.session_id;
                addMessage('bot', data.message);
            }
            
            // Send message
            async function sendMessage() {
                const input = document.getElementById('message-input');
                const message = input.value.trim();
                if (!message || !sessionId) return;
                
                addMessage('user', message);
                input.value = '';
                
                const response = await fetch('/api/chat/message', {
                    method: 'POST',
                    headers: {'Content-Type': 'application/json'},
                    body: JSON.stringify({
                        session_id: sessionId,
                        user_id: userId,
                        message: message
                    })
                });
                const data = await response.json();
                addMessage('bot', data.response || data.message);
            }
            
            // Add message to chat
            function addMessage(sender, message) {
                const chatContainer = document.getElementById('chat-container');
                const messageDiv = document.createElement('div');
                messageDiv.className = 'message ' + sender;
                
                // Convert markdown-style bold to HTML
                const formattedMessage = message
                    .replace(/\\*\\*(.*?)\\*\\*/g, '<strong>$1</strong>')
                    .replace(/\\n/g, '<br>');
                
                messageDiv.innerHTML = formattedMessage;
                chatContainer.appendChild(messageDiv);
                chatContainer.scrollTop = chatContainer.scrollHeight;
            }
            
            // Event listeners
            document.getElementById('send-button').onclick = sendMessage;
            document.getElementById('message-input').onkeypress = (e) => {
                if (e.key === 'Enter') sendMessage();
            };
            
            // Start chat on load
            startChat();
        </script>
    </body>
    </html>
    ''', tunnel_url=CLOUDFLARE_TUNNEL_URL, api_key=API_KEY)

@app.route('/api/debug/tickets', methods=['GET'])
@require_api_key
def debug_tickets():
    """Debug endpoint to see all tickets in the system"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({'error': 'Database connection failed'}), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get ALL tickets
        cursor.execute("""
            SELECT 
                ticket_id,
                source,
                sender,
                user_id,
                subject,
                approval_status,
                status,
                created_at,
                approved_at
            FROM tickets
            ORDER BY created_at DESC
        """)
        
        all_tickets = cursor.fetchall()
        
        # Get approved tickets
        cursor.execute("""
            SELECT 
                ticket_id,
                source,
                sender,
                user_id,
                subject,
                approval_status,
                status
            FROM tickets
            WHERE approval_status = 'approved'
        """)
        
        approved_tickets = cursor.fetchall()
        
        # Check for orphaned folders
        folders_in_storage = []
        if os.path.exists(BASE_STORAGE_PATH):
            folders_in_storage = [f for f in os.listdir(BASE_STORAGE_PATH) 
                                if not f.startswith('.')]
        
        cursor.close()
        conn.close()
        
        # Convert datetime objects to strings
        for ticket in all_tickets:
            for key, value in ticket.items():
                if isinstance(value, datetime):
                    ticket[key] = value.isoformat()
        
        for ticket in approved_tickets:
            for key, value in ticket.items():
                if isinstance(value, datetime):
                    ticket[key] = value.isoformat()
        
        return jsonify({
            'total_tickets': len(all_tickets),
            'approved_tickets': len(approved_tickets),
            'folders_in_storage': len(folders_in_storage),
            'all_tickets': all_tickets,
            'approved_tickets_list': approved_tickets,
            'storage_folders': folders_in_storage
        })
        
    except Exception as e:
        logger.error(f"Error in debug_tickets: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/health', methods=['GET'])
def health_check():
    """Health check endpoint"""
    conn = get_db_connection()
    db_status = "connected" if conn else "disconnected"
    
    if conn:
        conn.close()
    
    # Check storage directory
    storage_status = "accessible" if os.path.exists(BASE_STORAGE_PATH) else "not_found"
    
    # Check if filtering module is available
    filtering_module_status = "not_found"
    filtering_module_error = None
    try:
        from resume_filter5 import UpdatedResumeFilteringSystem
        filtering_module_status = "available"
    except ImportError as e:
        filtering_module_error = str(e)
        try:
            from resume_filter5 import UpdatedResumeFilteringSystem
            filtering_module_status = "available (as resume_filter5)"
        except ImportError as e2:
            filtering_module_error = f"resume_filter5: {e}, resume_filter: {e2}"
    
    return jsonify({
        'status': 'ok' if db_status == "connected" else 'error',
        'database': db_status,
        'tunnel': 'active' if CLOUDFLARE_TUNNEL_URL else 'inactive',
        'public_url': CLOUDFLARE_TUNNEL_URL,
        'storage': storage_status,
        'filtering_module': filtering_module_status,
        'filtering_module_error': filtering_module_error,
        'chat_enabled': True,
        'api_enabled': True,
        'timestamp': datetime.now().isoformat()
    })

# ============================================
# CHAT API ENDPOINTS
# ============================================

@app.route('/api/chat/start', methods=['POST'])
@require_api_key
def start_chat():
    """Start a new chat session"""
    try:
        data = request.json
        user_id = data.get('user_id', 'anonymous')
        
        result = chat_bot.start_session(user_id)
        return jsonify(result)
    
    except Exception as e:
        logger.error(f"Error starting chat: {e}")
        return jsonify({
            'error': 'Failed to start chat session',
            'message': str(e)
        }), 500

@app.route('/api/chat/message', methods=['POST'])
@require_api_key
def send_message():
    """Send a message to the chat bot"""
    try:
        data = request.json
        
        session_id = data.get('session_id')
        user_id = data.get('user_id')
        message = data.get('message')
        
        if not all([session_id, user_id, message]):
            return jsonify({
                'error': 'Missing required fields',
                'required': ['session_id', 'user_id', 'message']
            }), 400
        
        # Check if this is an authenticated HR user
        authenticated_user_email = None
        if 'Authorization' in request.headers:
            try:
                token = request.headers['Authorization'].replace('Bearer ', '')
                payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
                if payload.get('role') == 'hr':
                    authenticated_user_email = payload.get('email')
                    logger.info(f"Authenticated HR user: {authenticated_user_email}")
            except Exception as e:
                logger.warning(f"Failed to decode JWT token: {e}")
        
        # Pass the authenticated user email to the chat bot
        bot_response = chat_bot.process_message(session_id, user_id, message, authenticated_user_email)
        
        # Fix the response format for React frontend compatibility
        formatted_response = {
            'success': True,
            'response': bot_response.get('message', ''),  # Map 'message' to 'response'
            'message': bot_response.get('message', ''),   # Also keep as 'message'
            'metadata': bot_response.get('metadata', {}),
            'session_id': session_id,
            'timestamp': datetime.now().isoformat()
        }
        
        return jsonify(formatted_response)
    
    except Exception as e:
        logger.error(f"Error processing message: {e}")
        return jsonify({
            'error': 'Failed to process message',
            'message': str(e)
        }), 500

@app.route('/api/chat/history/<session_id>', methods=['GET'])
@require_api_key
def get_chat_history(session_id):
    """Get chat history for a session"""
    try:
        limit = request.args.get('limit', 50, type=int)
        messages = chat_bot.session_manager.get_messages(session_id, limit)
        
        formatted_messages = []
        for msg in messages:
            formatted_messages.append({
                'id': msg.get('message_id'),
                'sender': msg['sender_type'],
                'message': msg['message_content'],
                'metadata': msg.get('message_metadata'),
                'timestamp': msg['timestamp'].isoformat() if msg.get('timestamp') else None
            })
        
        return jsonify({
            'session_id': session_id,
            'messages': formatted_messages,
            'count': len(formatted_messages)
        })
    
    except Exception as e:
        logger.error(f"Error fetching history: {e}")
        return jsonify({
            'error': 'Failed to fetch chat history',
            'message': str(e)
        }), 500

# ============================================
# RESUME MANAGEMENT ENDPOINTS
# ============================================

@app.route('/api/tickets/<ticket_id>/approve', methods=['POST'])
@require_api_key
def approve_ticket_and_create_folder(ticket_id):
    """Approve a ticket and create its folder with enhanced logging"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get ticket details
        cursor.execute("""
            SELECT ticket_id, subject, approval_status, sender, created_at
            FROM tickets
            WHERE ticket_id = %s
        """, (ticket_id,))
        
        ticket = cursor.fetchone()
        
        if not ticket:
            cursor.close()
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Ticket not found'
            }), 404
        
        # Update approval status if not already approved
        if ticket['approval_status'] != 'approved':
            cursor.execute("""
                UPDATE tickets 
                SET approval_status = 'approved', 
                    approved_at = NOW(),
                    status = 'active'
                WHERE ticket_id = %s
            """, (ticket_id,))
            conn.commit()
            
            logger.info(f"Ticket {ticket_id} approved by HR manager")
        
        cursor.close()
        conn.close()
        
        # Ensure folder exists (create if it doesn't)
        folder_path = ensure_job_folder_exists(ticket_id, ticket['subject'])
        
        if folder_path:
            # Get folder information
            folder_info = get_job_folder_info(ticket_id)
            
            return jsonify({
                'success': True,
                'message': f'Job {ticket_id} approved and folder created successfully',
                'data': {
                    'ticket_id': ticket_id,
                    'job_title': ticket['subject'],
                    'approved_by': 'HR Manager',
                    'approved_at': datetime.now().isoformat(),
                    'folder_info': folder_info
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to create job folder'
            }), 500
            
    except Exception as e:
        logger.error(f"Error approving ticket: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/update-job-details', methods=['POST'])
@require_api_key
def update_job_details_endpoint(ticket_id):
    """Update job details file when ticket information changes"""
    try:
        success = update_job_details_in_folder(ticket_id)
        
        if success:
            return jsonify({
                'success': True,
                'message': f'Job details updated for ticket {ticket_id}'
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to update job details'
            }), 500
            
    except Exception as e:
        logger.error(f"Error updating job details: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500


    """Upload a resume for a specific ticket"""
    try:
        # Check if the ticket exists and is approved
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT ticket_id, subject, approval_status
            FROM tickets
            WHERE ticket_id = %s
        """, (ticket_id,))
        
        ticket = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not ticket:
            return jsonify({
                'success': False,
                'error': 'Ticket not found'
            }), 404
        
        if ticket['approval_status'] != 'approved':
            return jsonify({
                'success': False,
                'error': 'Ticket must be approved before uploading resumes'
            }), 400
        
        # Check if file is in request
        if 'resume' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400
        
        file = request.files['resume']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'error': f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Get applicant details from form data
        applicant_name = request.form.get('applicant_name', 'Unknown Applicant')
        applicant_email = request.form.get('applicant_email', 'No email provided')
        
        # Ensure folder exists (create if it doesn't)
        folder_path = ensure_job_folder_exists(ticket_id, ticket['subject'])
        if not folder_path:
            return jsonify({
                'success': False,
                'error': 'Failed to create job folder'
            }), 500
        
        # Save the resume
        saved_path = save_resume_to_ticket(
            ticket_id, 
            file, 
            applicant_name, 
            applicant_email
        )
        
        if saved_path:
            # Get updated folder information
            folder_info = get_job_folder_info(ticket_id)
            
            return jsonify({
                'success': True,
                'message': 'Resume uploaded successfully',
                'data': {
                    'ticket_id': ticket_id,
                    'job_title': ticket['subject'],
                    'applicant_name': applicant_name,
                    'applicant_email': applicant_email,
                    'filename': os.path.basename(saved_path),
                    'file_size': os.path.getsize(saved_path),
                    'uploaded_at': datetime.now().isoformat(),
                    'folder_info': folder_info
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save resume'
            }), 500
            
    except Exception as e:
        logger.error(f"Error uploading resume: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/resumes', methods=['GET'])
@require_api_key
def get_resumes(ticket_id):
    """Get list of all resumes for a ticket"""
    try:
        resumes = get_ticket_resumes(ticket_id)
        
        return jsonify({
            'success': True,
            'data': {
                'ticket_id': ticket_id,
                'resume_count': len(resumes),
                'resumes': resumes
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting resumes: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/resumes/<filename>', methods=['GET'])
@require_api_key
def download_resume(ticket_id, filename):
    """Download a specific resume"""
    try:
        # Find the ticket folder
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            return jsonify({
                'success': False,
                'error': 'Ticket folder not found'
            }), 404
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        file_path = os.path.join(folder_path, secure_filename(filename))
        
        if not os.path.exists(file_path):
            return jsonify({
                'success': False,
                'error': 'Resume not found'
            }), 404
        
        return send_file(file_path, as_attachment=True)
        
    except Exception as e:
        logger.error(f"Error downloading resume: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/maintenance/create-folders', methods=['POST'])
@require_api_key
def create_existing_folders_endpoint():
    """Endpoint to create folders for all existing approved tickets"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get all approved tickets
        cursor.execute("""
            SELECT ticket_id, subject
            FROM tickets
            WHERE approval_status = 'approved'
        """)
        
        approved_tickets = cursor.fetchall()
        results = {
            'created': [],
            'existing': [],
            'failed': []
        }
        
        for ticket in approved_tickets:
            ticket_id = ticket['ticket_id']
            
            # Check if folder already exists
            ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                            if f.startswith(f"{ticket_id}_")]
            
            if ticket_folders:
                results['existing'].append({
                    'ticket_id': ticket_id,
                    'folder': ticket_folders[0]
                })
            else:
                # Create folder
                folder_path = create_ticket_folder(ticket_id, ticket['subject'])
                if folder_path:
                    results['created'].append({
                        'ticket_id': ticket_id,
                        'folder': os.path.basename(folder_path)
                    })
                else:
                    results['failed'].append({
                        'ticket_id': ticket_id,
                        'reason': 'Failed to create folder'
                    })
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'total_approved': len(approved_tickets),
                'folders_created': len(results['created']),
                'folders_existing': len(results['existing']),
                'folders_failed': len(results['failed']),
                'details': results
            }
        })
        
    except Exception as e:
        logger.error(f"Error in create_existing_folders_endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/diagnostics/filtering', methods=['GET'])
@require_api_key
def check_filtering_system():
    """Diagnostic endpoint to check filtering system availability"""
    diagnostics = {
        'module_check': {},
        'system_info': {
            'python_version': sys.version,
            'current_directory': os.getcwd(),
            'python_path': sys.path[:5]  # First 5 paths
        },
        'required_modules': {}
    }
    
    # Check main filtering module
    try:
        from resume_filter5 import UpdatedResumeFilteringSystem
        diagnostics['module_check']['resume_filter5'] = 'available'
        diagnostics['module_check']['class'] = 'UpdatedResumeFilteringSystem found'
    except ImportError as e:
        diagnostics['module_check']['resume_filter5'] = f'not found: {str(e)}'
        
        # Try alternative name
        try:
            from resume_filter4 import UpdatedResumeFilteringSystem
            diagnostics['module_check']['resume_filter4'] = 'available'
            diagnostics['module_check']['class'] = 'UpdatedResumeFilteringSystem found in resume_filter4'
        except ImportError as e2:
            diagnostics['module_check']['resume_filter4'] = f'not found: {str(e2)}'
    
    # Check for file existence
    files_to_check = ['resume_filter5.py', 'resume_filter4.py', 'ai_bot3.py']
    diagnostics['files'] = {}
    
    for filename in files_to_check:
        if os.path.exists(filename):
            diagnostics['files'][filename] = {
                'exists': True,
                'size': os.path.getsize(filename),
                'readable': os.access(filename, os.R_OK)
            }
        else:
            diagnostics['files'][filename] = {'exists': False}
    
    # Check required dependencies
    required_modules = ['openai', 'PyPDF2', 'python-docx', 'tiktoken', 'pathlib']
    for module in required_modules:
        try:
            __import__(module)
            diagnostics['required_modules'][module] = 'installed'
        except ImportError:
            diagnostics['required_modules'][module] = 'not installed'
    
    # Check OpenAI API key
    diagnostics['openai_api_key'] = 'set' if os.environ.get('OPENAI_API_KEY') else 'not set'
    
    return jsonify({
        'success': True,
        'diagnostics': diagnostics
    })

# ============================================
# RESUME FILTERING ENDPOINTS - WITH AI INTEGRATION
# ============================================

@app.route('/api/tickets/<ticket_id>/filter-resumes', methods=['POST'])
@require_api_key
def trigger_resume_filtering(ticket_id):
    """Trigger resume filtering for a specific ticket"""
    try:
        # Check if ticket exists and has resumes
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            return jsonify({
                'success': False,
                'error': 'Ticket folder not found'
            }), 404
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        
        # Check if filtering is already in progress
        filtering_lock_file = os.path.join(folder_path, '.filtering_in_progress')
        if os.path.exists(filtering_lock_file):
            return jsonify({
                'success': False,
                'error': 'Filtering is already in progress for this ticket',
                'status': 'in_progress'
            }), 409
        
        # Check if there are resumes to filter
        resume_files = [f for f in os.listdir(folder_path) 
                       if f.endswith(('.pdf', '.doc', '.docx', '.txt', '.rtf'))]
        
        if not resume_files:
            return jsonify({
                'success': False,
                'error': 'No resumes found in ticket folder',
                'resume_count': 0
            }), 400
        
        # Check if filtering results already exist
        filtering_results_path = os.path.join(folder_path, 'filtering_results')
        
        # Safely get the force parameter
        force_refilter = False
        try:
            if request.is_json and request.json:
                force_refilter = request.json.get('force', False)
        except:
            # If JSON parsing fails, just use default
            force_refilter = False
        
        if os.path.exists(filtering_results_path) and not force_refilter:
            result_files = list(Path(filtering_results_path).glob('final_results_*.json'))
            if result_files:
                # Get the latest result
                latest_result = max(result_files, key=lambda x: x.stat().st_mtime)
                
                with open(latest_result, 'r') as f:
                    filtering_data = json.load(f)
                
                return jsonify({
                    'success': True,
                    'message': 'Filtering results already exist. Use force=true to re-run.',
                    'status': 'completed',
                    'data': {
                        'filtered_at': filtering_data.get('timestamp'),
                        'total_resumes': filtering_data.get('summary', {}).get('total_resumes', 0),
                        'top_candidates_count': len(filtering_data.get('final_top_5', filtering_data.get('top_5_candidates', [])))
                    }
                })
        
        # Create lock file
        with open(filtering_lock_file, 'w') as f:
            f.write(json.dumps({
                'started_at': datetime.now().isoformat(),
                'pid': os.getpid()
            }))
        
        # Run filtering in a background thread
        def run_filtering():
            try:
                logger.info(f"Starting AI filtering for ticket {ticket_id}")
                logger.info(f"Folder path: {folder_path}")
                logger.info(f"Resume files found: {resume_files}")
                
                # Try to import the filtering system
                try:
                    from resume_filter5 import UpdatedResumeFilteringSystem
                    logger.info("Successfully imported UpdatedResumeFilteringSystem from resume_filter5")
                except ImportError as e:
                    logger.error(f"Failed to import resume_filter5: {e}")
                    # Try alternative import
                    try:
                        from resume_filter4 import UpdatedResumeFilteringSystem
                        logger.info("Successfully imported from resume_filter4")
                    except ImportError as e2:
                        logger.error(f"Failed to import resume_filter4: {e2}")
                        raise ImportError(f"Could not import filtering system: resume_filter5: {e} / resume_filter4: {e2}")
                
                # Create and run the filtering system
                logger.info("Creating filter system instance...")
                filter_system = UpdatedResumeFilteringSystem(folder_path)
                
                logger.info("Running filter_resumes()...")
                results = filter_system.filter_resumes()
                
                if "error" not in results:
                    logger.info(f"AI filtering completed successfully for ticket {ticket_id}")
                    
                    # Create a status file for the API
                    status_file = os.path.join(folder_path, 'filtering_status.json')
                    with open(status_file, 'w') as f:
                        json.dump({
                            'status': 'completed',
                            'completed_at': datetime.now().isoformat(),
                            'total_resumes': results.get('summary', {}).get('total_resumes', 0),
                            'top_candidates': len(results.get('final_top_5', results.get('top_5_candidates', []))),
                            'success': True
                        }, f)
                else:
                    logger.error(f"AI filtering failed for ticket {ticket_id}: {results.get('error')}")
                    
                    # Create error status file
                    status_file = os.path.join(folder_path, 'filtering_status.json')
                    with open(status_file, 'w') as f:
                        json.dump({
                            'status': 'failed',
                            'completed_at': datetime.now().isoformat(),
                            'error': results.get('error'),
                            'success': False
                        }, f)
                
            except ImportError as e:
                error_msg = f"Import error: {str(e)}"
                logger.error(f"Import error running AI filtering for ticket {ticket_id}: {error_msg}")
                
                # Create error status file
                status_file = os.path.join(folder_path, 'filtering_status.json')
                with open(status_file, 'w') as f:
                    json.dump({
                        'status': 'failed',
                        'completed_at': datetime.now().isoformat(),
                        'error': error_msg,
                        'success': False
                    }, f)
                    
            except Exception as e:
                error_msg = f"{type(e).__name__}: {str(e)}"
                logger.error(f"Error running AI filtering for ticket {ticket_id}: {error_msg}")
                import traceback
                full_traceback = traceback.format_exc()
                logger.error(f"Full traceback:\n{full_traceback}")
                
                # Create error status file
                status_file = os.path.join(folder_path, 'filtering_status.json')
                with open(status_file, 'w') as f:
                    json.dump({
                        'status': 'failed',
                        'completed_at': datetime.now().isoformat(),
                        'error': error_msg,
                        'traceback': full_traceback,
                        'success': False
                    }, f)
            
            finally:
                # Remove lock file
                if os.path.exists(filtering_lock_file):
                    os.remove(filtering_lock_file)
                logger.info(f"Filtering thread completed for ticket {ticket_id}")
        
        # Start filtering in background thread
        filtering_thread = threading.Thread(
            target=run_filtering,
            name=f"filtering-{ticket_id}",
            daemon=True
        )
        filtering_thread.start()
        
        return jsonify({
            'success': True,
            'message': 'Resume filtering started',
            'status': 'started',
            'data': {
                'ticket_id': ticket_id,
                'resume_count': len(resume_files),
                'started_at': datetime.now().isoformat()
            }
        })
        
    except Exception as e:
        logger.error(f"Error triggering resume filtering: {e}")
        import traceback
        traceback.print_exc()
        
        # Clean up lock file if error
        if 'filtering_lock_file' in locals() and os.path.exists(filtering_lock_file):
            os.remove(filtering_lock_file)
        
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/top-resumes', methods=['GET'])
@require_api_key
def get_top_resumes(ticket_id):
    """Get top-ranked resumes with their details and scores"""
    try:
        # Get parameters
        include_content = request.args.get('include_content', 'false').lower() == 'true'
        top_n = min(int(request.args.get('top', 5)), 10)  # Max 10 resumes
        
        # Find the ticket folder
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            return jsonify({
                'success': False,
                'error': 'Ticket folder not found'
            }), 404
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        filtering_results_path = os.path.join(folder_path, 'filtering_results')
        
        if not os.path.exists(filtering_results_path):
            return jsonify({
                'success': False,
                'error': 'No filtering results found. Please run resume filtering first.'
            }), 404
        
        # Get the latest filtering results
        result_files = list(Path(filtering_results_path).glob('final_results*.json'))
        if not result_files:
            return jsonify({
                'success': False,
                'error': 'No filtering results found'
            }), 404
        
        latest_result = max(result_files, key=lambda x: x.stat().st_mtime)
        
        with open(latest_result, 'r') as f:
            filtering_data = json.load(f)
        
        # Get top candidates
        top_candidates = filtering_data.get('final_top_5', filtering_data.get('top_5_candidates', []))[:top_n]
        
        # Get job requirements used
        job_requirements = filtering_data.get('latest_requirements', {})
        
        # Check if any candidates meet minimum requirements
        warnings = []
        min_experience = 5  # From "5-8 years"
        
        if top_candidates:
            # Check experience requirement
            if all(c.get('detected_experience_years', 0) < min_experience for c in top_candidates):
                warnings.append(f"No candidates meet the minimum experience requirement of {min_experience} years")
            
            # Check location requirement
            if all(c.get('location_score', 0) == 0 for c in top_candidates):
                warnings.append(f"No candidates match the required location: {job_requirements.get('location', 'Unknown')}")
            
            # Check if scores are too low
            if all(c.get('final_score', 0) < 0.6 for c in top_candidates):
                warnings.append("All candidates scored below 60% match")
        
        # Prepare response with resume details
        candidates_with_details = []
        
        for i, candidate in enumerate(top_candidates):
            candidate_data = {
                'rank': i + 1,
                'filename': candidate['filename'],
                'score': candidate['final_score'],  # Add numeric score for frontend compatibility
                'scores': {
                    'overall': candidate['final_score'],  # Return numeric value instead of formatted string
                    'skills': candidate['skill_score'],
                    'experience': candidate['experience_score'],
                    'location': candidate['location_score'],
                    'professional_development': candidate.get('professional_development_score', 0)
                },
                'matched_skills': candidate.get('matched_skills', []),
                'missing_skills': [s for s in job_requirements.get('tech_stack', []) 
                                 if s not in candidate.get('matched_skills', [])],
                'experience_years': candidate.get('detected_experience_years', 0),
                'skill_match_ratio': f"{len(candidate.get('matched_skills', []))}/{len(job_requirements.get('tech_stack', []))}",
                'file_path': candidate.get('file_path'),
                'key_highlights': candidate.get('professional_development', {}).get('summary', {}).get('key_highlights', []),
                
                # Add professional development details
                'professional_development': {
                    'score': candidate.get('professional_development_score', 0),  # Return numeric value
                    'level': candidate.get('professional_development', {}).get('professional_development_level', 'Unknown'),
                    'summary': candidate.get('professional_development', {}).get('summary', {}),
                    'key_highlights': candidate.get('professional_development', {}).get('summary', {}).get('key_highlights', []),
                    'details': {
                        'certifications': {
                            'count': candidate.get('professional_development', {}).get('summary', {}).get('total_certifications', 0),
                            'list': candidate.get('professional_development', {}).get('component_scores', {}).get('certifications', {}).get('certifications_found', []),
                            'categories': candidate.get('professional_development', {}).get('summary', {}).get('certification_categories', [])
                        },
                        'learning_platforms': {
                            'count': candidate.get('professional_development', {}).get('summary', {}).get('learning_platforms_used', 0),
                            'platforms': candidate.get('professional_development', {}).get('component_scores', {}).get('online_learning', {}).get('platforms_found', []),
                            'estimated_courses': candidate.get('professional_development', {}).get('summary', {}).get('estimated_courses_completed', 0)
                        },
                        'conferences': {
                            'attended': candidate.get('professional_development', {}).get('summary', {}).get('conferences_attended', 0),
                            'speaker': candidate.get('professional_development', {}).get('summary', {}).get('conference_speaker', False),
                            'events': candidate.get('professional_development', {}).get('component_scores', {}).get('conferences', {}).get('events_found', [])
                        },
                        'content_creation': {
                            'is_creator': candidate.get('professional_development', {}).get('summary', {}).get('content_creator', False),
                            'types': candidate.get('professional_development', {}).get('summary', {}).get('content_types', []),
                            'platforms': candidate.get('professional_development', {}).get('component_scores', {}).get('content_creation', {}).get('content_platforms', [])
                        }
                    }
                }
            }
            
            # Get metadata from metadata.json
            metadata_path = os.path.join(folder_path, 'metadata.json')
            if os.path.exists(metadata_path):
                with open(metadata_path, 'r') as f:
                    metadata = json.load(f)
                
                # Find matching resume metadata
                for resume_info in metadata.get('resumes', []):
                    if resume_info['filename'] == candidate['filename']:
                        candidate_data['applicant_name'] = resume_info.get('applicant_name', 'Unknown')
                        candidate_data['applicant_email'] = resume_info.get('applicant_email', 'Not provided')
                        candidate_data['uploaded_at'] = resume_info.get('uploaded_at')
                        break
            
            # Add download URL if tunnel is active
            if CLOUDFLARE_TUNNEL_URL:
                candidate_data['download_url'] = f"{CLOUDFLARE_TUNNEL_URL}/api/tickets/{ticket_id}/resumes/{candidate['filename']}?api_key={API_KEY}"
            
            # Include resume content if requested
            if include_content:
                resume_path = os.path.join(folder_path, candidate['filename'])
                if os.path.exists(resume_path):
                    try:
                        with open(resume_path, 'rb') as f:
                            resume_content = f.read()
                            candidate_data['resume_base64'] = base64.b64encode(resume_content).decode('utf-8')
                            candidate_data['resume_size'] = len(resume_content)
                    except Exception as e:
                        logger.error(f"Error reading resume {candidate['filename']}: {e}")
            
            candidates_with_details.append(candidate_data)
        
        # Get AI analysis if available
        ai_analysis = {
            'stage1_review': filtering_data.get('stage1_results', {}).get('agent_review', ''),
            'stage2_analysis': filtering_data.get('stage2_results', {}).get('detailed_analysis', ''),
            'qa_assessment': filtering_data.get('qa_review', {}).get('qa_assessment', '')
        }
        
        # Get scoring weights used
        scoring_weights = {}
        if top_candidates:
            scoring_weights = top_candidates[0].get('scoring_weights', {})
        
        return jsonify({
            'success': True,
            'warnings': warnings,  # Add warnings about candidate quality
            'data': {
                'ticket_id': ticket_id,
                'filtered_at': filtering_data.get('timestamp'),
                'job_position': filtering_data.get('position'),
                'job_requirements': job_requirements,
                'scoring_weights': {
                    'skills': f"{scoring_weights.get('skills', 0.4):.0%}",
                    'experience': f"{scoring_weights.get('experience', 0.3):.0%}",
                    'location': f"{scoring_weights.get('location', 0.1):.0%}",
                    'professional_development': f"{scoring_weights.get('professional_dev', 0.2):.0%}"
                },
                'summary': {
                    'total_resumes_processed': filtering_data.get('summary', {}).get('total_resumes', 0),
                    'top_candidates_returned': len(candidates_with_details)
                },
                'top_candidates': candidates_with_details,
                'ai_analysis': ai_analysis
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting top resumes: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/filtering-report', methods=['GET'])
@require_api_key
def get_filtering_report(ticket_id):
    """Get the complete filtering report for a ticket"""
    try:
        # Find the ticket folder
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            return jsonify({
                'success': False,
                'error': 'Ticket folder not found'
            }), 404
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        filtering_results_path = os.path.join(folder_path, 'filtering_results')
        
        if not os.path.exists(filtering_results_path):
            return jsonify({
                'success': False,
                'error': 'No filtering results found'
            }), 404
        
        # Get the latest summary report
        report_files = list(Path(filtering_results_path).glob('summary_report_*.txt'))
        if not report_files:
            return jsonify({
                'success': False,
                'error': 'No summary report found'
            }), 404
        
        latest_report = max(report_files, key=lambda x: x.stat().st_mtime)
        
        with open(latest_report, 'r') as f:
            report_content = f.read()
        
        # Also get the JSON results
        result_files = list(Path(filtering_results_path).glob('final_results_*.json'))
        if result_files:
            latest_result = max(result_files, key=lambda x: x.stat().st_mtime)
            with open(latest_result, 'r') as f:
                json_results = json.load(f)
        else:
            json_results = {}
        
        return jsonify({
            'success': True,
            'data': {
                'ticket_id': ticket_id,
                'report_text': report_content,
                'report_filename': latest_report.name,
                'generated_at': json_results.get('timestamp'),
                'summary_stats': json_results.get('summary', {}),
                'files': {
                    'report': str(latest_report),
                    'json_results': str(latest_result) if result_files else None
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting filtering report: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/send-top-resumes', methods=['POST'])
@require_api_key
def send_top_resumes_email(ticket_id):
    """Send top resumes via email or webhook"""
    try:
        # Get request data
        data = request.get_json()
        recipient_email = data.get('email')
        webhook_url = data.get('webhook_url')
        include_resumes = data.get('include_resumes', True)
        top_n = min(data.get('top_n', 5), 10)
        
        if not recipient_email and not webhook_url:
            return jsonify({
                'success': False,
                'error': 'Either email or webhook_url is required'
            }), 400
        
        # Get top resumes data
        response = get_top_resumes(ticket_id)
        resume_data = response.get_json()
        
        if not resume_data['success']:
            return response
        
        top_candidates = resume_data['data']['top_candidates'][:top_n]
        
        # Prepare email/webhook payload
        payload = {
            'ticket_id': ticket_id,
            'job_position': resume_data['data']['job_position'],
            'filtered_at': resume_data['data']['filtered_at'],
            'top_candidates': []
        }
        
        # Add candidate details
        for candidate in top_candidates:
            candidate_info = {
                'rank': candidate['rank'],
                'name': candidate.get('applicant_name', 'Unknown'),
                'email': candidate.get('applicant_email', ''),
                'filename': candidate['filename'],
                'scores': candidate['scores'],
                'matched_skills': candidate['matched_skills'],
                'experience_years': candidate['experience_years']
            }
            
            # Add download link
            if CLOUDFLARE_TUNNEL_URL:
                candidate_info['download_url'] = f"{CLOUDFLARE_TUNNEL_URL}/api/tickets/{ticket_id}/resumes/{candidate['filename']}"
            
            payload['top_candidates'].append(candidate_info)
        
        # If webhook URL provided, send to webhook
        if webhook_url:
            import requests
            try:
                webhook_response = requests.post(webhook_url, json=payload, timeout=30)
                if webhook_response.status_code == 200:
                    return jsonify({
                        'success': True,
                        'message': 'Top resumes sent to webhook successfully'
                    })
                else:
                    return jsonify({
                        'success': False,
                        'error': f'Webhook returned status {webhook_response.status_code}'
                    }), 500
            except Exception as webhook_error:
                logger.error(f"Webhook error: {webhook_error}")
                return jsonify({
                    'success': False,
                    'error': f'Failed to send to webhook: {str(webhook_error)}'
                }), 500
        
        # If email provided, you would implement email sending here
        if recipient_email:
            # This is a placeholder - you would implement actual email sending
            # using a service like SendGrid, AWS SES, or SMTP
            return jsonify({
                'success': True,
                'message': f'Email functionality not implemented. Would send to: {recipient_email}',
                'payload': payload
            })
        
    except Exception as e:
        logger.error(f"Error sending top resumes: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/filtering-status', methods=['GET'])
@require_api_key
def get_filtering_status(ticket_id):
    """Check if filtering has been done for a ticket"""
    try:
        # Find the ticket folder
        ticket_folders = [f for f in os.listdir(BASE_STORAGE_PATH) 
                         if f.startswith(f"{ticket_id}_")]
        
        if not ticket_folders:
            return jsonify({
                'success': False,
                'status': 'no_folder',
                'message': 'Ticket folder not found'
            })
        
        folder_path = os.path.join(BASE_STORAGE_PATH, ticket_folders[0])
        
        # Check for resumes
        resume_count = len([f for f in os.listdir(folder_path) 
                           if f.endswith(('.pdf', '.doc', '.docx', '.txt', '.rtf'))])
        
        # Check if filtering is in progress
        filtering_lock_file = os.path.join(folder_path, '.filtering_in_progress')
        if os.path.exists(filtering_lock_file):
            with open(filtering_lock_file, 'r') as f:
                lock_data = json.load(f)
            
            return jsonify({
                'success': True,
                'data': {
                    'ticket_id': ticket_id,
                    'folder_exists': True,
                    'resume_count': resume_count,
                    'status': 'in_progress',
                    'filtering_started_at': lock_data.get('started_at'),
                    'message': 'Filtering is currently in progress'
                }
            })
        
        # Check for status file (for recently completed/failed filtering)
        status_file = os.path.join(folder_path, 'filtering_status.json')
        if os.path.exists(status_file):
            with open(status_file, 'r') as f:
                status_data = json.load(f)
            
            # If filtering failed, include error info
            if status_data.get('status') == 'failed':
                return jsonify({
                    'success': True,
                    'data': {
                        'ticket_id': ticket_id,
                        'folder_exists': True,
                        'resume_count': resume_count,
                        'status': 'failed',
                        'error': status_data.get('error'),
                        'failed_at': status_data.get('completed_at')
                    }
                })
        
        # Check for filtering results
        filtering_results_path = os.path.join(folder_path, 'filtering_results')
        has_filtering_results = os.path.exists(filtering_results_path)
        
        filtering_info = {}
        if has_filtering_results:
            result_files = list(Path(filtering_results_path).glob('final_results_*.json'))
            if result_files:
                latest_result = max(result_files, key=lambda x: x.stat().st_mtime)
                with open(latest_result, 'r') as f:
                    filtering_data = json.load(f)
                
                filtering_info = {
                    'filtered_at': filtering_data.get('timestamp'),
                    'total_processed': filtering_data.get('summary', {}).get('total_resumes', 0),
                    'top_candidates': len(filtering_data.get('final_top_5', filtering_data.get('top_5_candidates', []))),
                    'last_updated': datetime.fromtimestamp(latest_result.stat().st_mtime).isoformat()
                }
        
        return jsonify({
            'success': True,
            'data': {
                'ticket_id': ticket_id,
                'folder_exists': True,
                'resume_count': resume_count,
                'has_filtering_results': has_filtering_results,
                'filtering_info': filtering_info,
                'ready_for_filtering': resume_count > 0,
                'status': 'completed' if has_filtering_results else ('ready' if resume_count > 0 else 'no_resumes')
            }
        })
        
    except Exception as e:
        logger.error(f"Error checking filtering status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# JOB MANAGEMENT ENDPOINTS
# ============================================

@app.route('/api/jobs/approved', methods=['GET'])
@require_api_key
def get_approved_jobs():
    """Get all approved jobs with pagination and filtering (for public/candidate access)"""
    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 10)), 50)
        location_filter = request.args.get('location', '')
        skills_filter = request.args.get('skills', '')
        sort_by = request.args.get('sort', 'approved_at')
        order = request.args.get('order', 'desc')
        
        # Validate sort parameters
        allowed_sorts = ['created_at', 'approved_at', 'last_updated']
        if sort_by not in allowed_sorts:
            sort_by = 'approved_at'
        
        if order not in ['asc', 'desc']:
            order = 'desc'
        
        offset = (page - 1) * per_page
        
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # First, get all approved tickets (public access - no user filtering)
        cursor.execute("""
            SELECT 
                ticket_id,
                sender,
                subject,
                created_at,
                last_updated,
                approved_at,
                status
            FROM tickets
            WHERE approval_status = 'approved' 
                AND status != 'terminated'
            ORDER BY {} {}
            LIMIT %s OFFSET %s
        """.format(sort_by, order), (per_page, offset))
        
        tickets = cursor.fetchall()
        
        # For each ticket, get the LATEST value for each field
        jobs = []
        for ticket in tickets:
            ticket_id = ticket['ticket_id']
            
            # Get the latest value for each field using a subquery
            cursor.execute("""
                SELECT 
                    td1.field_name,
                    td1.field_value
                FROM ticket_details td1
                INNER JOIN (
                    SELECT field_name, MAX(created_at) as max_created_at
                    FROM ticket_details
                    WHERE ticket_id = %s
                    GROUP BY field_name
                ) td2 ON td1.field_name = td2.field_name 
                     AND td1.created_at = td2.max_created_at
                WHERE td1.ticket_id = %s
            """, (ticket_id, ticket_id))
            
            # Build the job details
            job_details = {}
            for row in cursor.fetchall():
                job_details[row['field_name']] = row['field_value']
            
            # Apply location filter if specified
            if location_filter and job_details.get('location', '').lower() != location_filter.lower():
                continue
            
            # Apply skills filter if specified
            if skills_filter:
                skill_list = [s.strip().lower() for s in skills_filter.split(',')]
                job_skills = job_details.get('required_skills', '').lower()
                if not any(skill in job_skills for skill in skill_list):
                    continue
            
            # Check if this job was updated after approval
            cursor.execute("""
                SELECT COUNT(*) as update_count
                FROM ticket_updates
                WHERE ticket_id = %s AND update_timestamp > %s
            """, (ticket_id, ticket['approved_at']))
            
            update_info = cursor.fetchone()
            updated_after_approval = update_info['update_count'] > 0
            
            # Check if folder exists and get resume count
            resumes = get_ticket_resumes(ticket_id)
            
            # Combine ticket info with job details
            job = {
                'ticket_id': ticket['ticket_id'],
                'sender': ticket['sender'],
                'subject': ticket['subject'],
                'created_at': serialize_datetime(ticket['created_at']),
                'last_updated': serialize_datetime(ticket['last_updated']),
                'approved_at': serialize_datetime(ticket['approved_at']),
                'status': ticket['status'],
                'job_title': job_details.get('job_title', 'NOT_FOUND'),
                'location': job_details.get('location', 'NOT_FOUND'),
                'experience_required': job_details.get('experience_required', 'NOT_FOUND'),
                'salary_range': job_details.get('salary_range', 'NOT_FOUND'),
                'job_description': job_details.get('job_description', 'NOT_FOUND'),
                'required_skills': job_details.get('required_skills', 'NOT_FOUND'),
                'employment_type': job_details.get('employment_type', 'NOT_FOUND'),
                'deadline': job_details.get('deadline', 'NOT_FOUND'),
                'updated_after_approval': updated_after_approval,
                'resume_count': len(resumes),
                'has_folder': len([f for f in os.listdir(BASE_STORAGE_PATH) if f.startswith(f"{ticket_id}_")]) > 0
            }
            
            jobs.append(job)
        
        # Get total count for pagination
        count_query = """
            SELECT COUNT(*) as total
            FROM tickets
            WHERE approval_status = 'approved' 
                AND status != 'terminated'
        """
        cursor.execute(count_query)
        total_count = cursor.fetchone()['total']
        
        cursor.close()
        conn.close()
        
        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        
        return jsonify({
            'success': True,
            'data': {
                'jobs': jobs,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_approved_jobs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/hr/jobs/approved', methods=['GET'])
@require_jwt_auth
def get_hr_approved_jobs():
    """Get approved jobs for HR users (only shows tickets created by the authenticated HR user)"""
    try:
        # Get query parameters
        page = int(request.args.get('page', 1))
        per_page = min(int(request.args.get('per_page', 10)), 50)
        location_filter = request.args.get('location', '')
        skills_filter = request.args.get('skills', '')
        sort_by = request.args.get('sort', 'approved_at')
        order = request.args.get('order', 'desc')
        
        # Validate sort parameters
        allowed_sorts = ['created_at', 'approved_at', 'last_updated']
        if sort_by not in allowed_sorts:
            sort_by = 'approved_at'
        
        if order not in ['asc', 'desc']:
            order = 'desc'
        
        offset = (page - 1) * per_page
        
        # Get authenticated user info
        user_id = request.user['user_id']
        user_email = request.user['email']
        
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get approved tickets created by this HR user only
        cursor.execute("""
            SELECT 
                ticket_id,
                sender,
                subject,
                created_at,
                last_updated,
                approved_at,
                status
            FROM tickets
            WHERE approval_status = 'approved' 
                AND status != 'terminated'
                AND (user_id = %s OR sender = %s)
            ORDER BY {} {}
            LIMIT %s OFFSET %s
        """.format(sort_by, order), (user_id, user_email, per_page, offset))
        
        tickets = cursor.fetchall()
        
        # For each ticket, get the LATEST value for each field
        jobs = []
        for ticket in tickets:
            ticket_id = ticket['ticket_id']
            
            # Get the latest value for each field using a subquery
            cursor.execute("""
                SELECT 
                    td1.field_name,
                    td1.field_value
                FROM ticket_details td1
                INNER JOIN (
                    SELECT field_name, MAX(created_at) as max_created_at
                    FROM ticket_details
                    WHERE ticket_id = %s
                    GROUP BY field_name
                ) td2 ON td1.field_name = td2.field_name 
                     AND td1.created_at = td2.max_created_at
                WHERE td1.ticket_id = %s
            """, (ticket_id, ticket_id))
            
            # Build the job details
            job_details = {}
            for row in cursor.fetchall():
                job_details[row['field_name']] = row['field_value']
            
            # Apply location filter if specified
            if location_filter and job_details.get('location', '').lower() != location_filter.lower():
                continue
            
            # Apply skills filter if specified
            if skills_filter:
                skill_list = [s.strip().lower() for s in skills_filter.split(',')]
                job_skills = job_details.get('required_skills', '').lower()
                if not any(skill in job_skills for skill in skill_list):
                    continue
            
            # Check if this job was updated after approval
            cursor.execute("""
                SELECT COUNT(*) as update_count
                FROM ticket_updates
                WHERE ticket_id = %s AND update_timestamp > %s
            """, (ticket_id, ticket['approved_at']))
            
            update_info = cursor.fetchone()
            updated_after_approval = update_info['update_count'] > 0
            
            # Check if folder exists and get resume count
            resumes = get_ticket_resumes(ticket_id)
            
            # Combine ticket info with job details
            job = {
                'ticket_id': ticket['ticket_id'],
                'sender': ticket['sender'],
                'subject': ticket['subject'],
                'created_at': serialize_datetime(ticket['created_at']),
                'last_updated': serialize_datetime(ticket['last_updated']),
                'approved_at': serialize_datetime(ticket['approved_at']),
                'status': ticket['status'],
                'job_title': job_details.get('job_title', 'NOT_FOUND'),
                'location': job_details.get('location', 'NOT_FOUND'),
                'experience_required': job_details.get('experience_required', 'NOT_FOUND'),
                'salary_range': job_details.get('salary_range', 'NOT_FOUND'),
                'job_description': job_details.get('job_description', 'NOT_FOUND'),
                'required_skills': job_details.get('required_skills', 'NOT_FOUND'),
                'employment_type': job_details.get('employment_type', 'NOT_FOUND'),
                'deadline': job_details.get('deadline', 'NOT_FOUND'),
                'updated_after_approval': updated_after_approval,
                'resume_count': len(resumes),
                'has_folder': len([f for f in os.listdir(BASE_STORAGE_PATH) if f.startswith(f"{ticket_id}_")]) > 0
            }
            
            jobs.append(job)
        
        # Get total count for pagination (filtered by user)
        count_query = """
            SELECT COUNT(*) as total
            FROM tickets
            WHERE approval_status = 'approved' 
                AND status != 'terminated'
                AND (user_id = %s OR sender = %s)
        """
        cursor.execute(count_query, (user_id, user_email))
        total_count = cursor.fetchone()['total']
        
        cursor.close()
        conn.close()
        
        # Calculate pagination info
        total_pages = (total_count + per_page - 1) // per_page
        
        return jsonify({
            'success': True,
            'data': {
                'jobs': jobs,
                'pagination': {
                    'page': page,
                    'per_page': per_page,
                    'total': total_count,
                    'total_pages': total_pages,
                    'has_next': page < total_pages,
                    'has_prev': page > 1
                }
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_hr_approved_jobs: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/jobs/<ticket_id>', methods=['GET'])
@require_api_key
def get_job_details(ticket_id):
    """Get detailed information about a specific job"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get ticket information
        cursor.execute("""
            SELECT * FROM tickets 
            WHERE ticket_id = %s
        """, (ticket_id,))
        
        ticket = cursor.fetchone()
        
        if not ticket:
            cursor.close()
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Job not found'
            }), 404
        
        # Get the LATEST value for each field
        cursor.execute("""
            SELECT 
                td1.field_name,
                td1.field_value,
                td1.created_at,
                td1.is_initial
            FROM ticket_details td1
            INNER JOIN (
                SELECT field_name, MAX(created_at) as max_created_at
                FROM ticket_details
                WHERE ticket_id = %s
                GROUP BY field_name
            ) td2 ON td1.field_name = td2.field_name 
                 AND td1.created_at = td2.max_created_at
            WHERE td1.ticket_id = %s
        """, (ticket_id, ticket_id))
        
        current_details = {}
        for row in cursor.fetchall():
            current_details[row['field_name']] = row['field_value']
        
        # Get complete history
        cursor.execute("""
            SELECT field_name, field_value, created_at, is_initial
            FROM ticket_details 
            WHERE ticket_id = %s
            ORDER BY field_name, created_at DESC
        """, (ticket_id,))
        
        all_details = cursor.fetchall()
        
        # Organize history by field
        detail_history = {}
        for row in all_details:
            field_name = row['field_name']
            if field_name not in detail_history:
                detail_history[field_name] = []
            
            detail_history[field_name].append({
                'value': row['field_value'],
                'updated_at': serialize_datetime(row['created_at']),
                'is_initial': row['is_initial']
            })
        
        # Get update history
        cursor.execute("""
            SELECT update_timestamp, updated_fields
            FROM ticket_updates
            WHERE ticket_id = %s
            ORDER BY update_timestamp DESC
        """, (ticket_id,))
        
        updates = []
        for row in cursor.fetchall():
            updates.append({
                'timestamp': serialize_datetime(row['update_timestamp']),
                'fields': json.loads(row['updated_fields']) if row['updated_fields'] else {}
            })
        
        # Convert datetime objects in ticket
        for key, value in ticket.items():
            ticket[key] = serialize_datetime(value)
        
        # Get resume information
        resumes = get_ticket_resumes(ticket_id)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'ticket': ticket,
                'current_details': current_details,
                'history': detail_history,
                'updates': updates,
                'is_approved': ticket['approval_status'] == 'approved',
                'updated_after_approval': len([u for u in updates if u['timestamp'] > ticket['approved_at']]) > 0 if ticket['approved_at'] else False,
                'resumes': resumes,
                'resume_count': len(resumes)
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_job_details: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/jobs/search', methods=['GET'])
@require_api_key
def search_jobs():
    """Search jobs by keyword"""
    try:
        query = request.args.get('q', '').strip()
        
        if not query:
            return jsonify({
                'success': False,
                'error': 'Search query is required'
            }), 400
        
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # First, get all approved tickets
        cursor.execute("""
            SELECT DISTINCT
                t.ticket_id,
                t.subject,
                t.created_at,
                t.approved_at,
                t.last_updated
            FROM tickets t
            WHERE t.approval_status = 'approved' 
                AND t.status != 'terminated'
            ORDER BY t.approved_at DESC
        """)
        
        tickets = cursor.fetchall()
        jobs = []
        
        for ticket in tickets:
            ticket_id = ticket['ticket_id']
            
            # Get latest values for this ticket
            cursor.execute("""
                SELECT 
                    td1.field_name,
                    td1.field_value
                FROM ticket_details td1
                INNER JOIN (
                    SELECT field_name, MAX(created_at) as max_created_at
                    FROM ticket_details
                    WHERE ticket_id = %s
                    GROUP BY field_name
                ) td2 ON td1.field_name = td2.field_name 
                     AND td1.created_at = td2.max_created_at
                WHERE td1.ticket_id = %s
            """, (ticket_id, ticket_id))
            
            job_details = {}
            for row in cursor.fetchall():
                job_details[row['field_name']] = row['field_value']
            
            # Check if search query matches any field
            search_text = query.lower()
            if (search_text in ticket['subject'].lower() or
                search_text in job_details.get('job_title', '').lower() or
                search_text in job_details.get('job_description', '').lower() or
                search_text in job_details.get('required_skills', '').lower() or
                search_text in job_details.get('location', '').lower()):
                
                job = {
                    'ticket_id': ticket['ticket_id'],
                    'subject': ticket['subject'],
                    'created_at': serialize_datetime(ticket['created_at']),
                    'approved_at': serialize_datetime(ticket['approved_at']),
                    'last_updated': serialize_datetime(ticket['last_updated']),
                    'job_title': job_details.get('job_title', 'NOT_FOUND'),
                    'location': job_details.get('location', 'NOT_FOUND'),
                    'experience_required': job_details.get('experience_required', 'NOT_FOUND'),
                    'salary_range': job_details.get('salary_range', 'NOT_FOUND'),
                    'job_description': job_details.get('job_description', 'NOT_FOUND'),
                    'required_skills': job_details.get('required_skills', 'NOT_FOUND'),
                    'employment_type': job_details.get('employment_type', 'NOT_FOUND'),
                    'deadline': job_details.get('deadline', 'NOT_FOUND')
                }
                jobs.append(job)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'query': query,
                'count': len(jobs),
                'jobs': jobs
            }
        })
        
    except Exception as e:
        logger.error(f"Error in search_jobs: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/stats', methods=['GET'])
@require_api_key
def get_statistics():
    """Get hiring statistics and analytics (system-wide)"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Overall statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tickets,
                SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) as approved_jobs,
                SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) as pending_approval,
                SUM(CASE WHEN approval_status = 'rejected' THEN 1 ELSE 0 END) as rejected_jobs,
                SUM(CASE WHEN status = 'terminated' THEN 1 ELSE 0 END) as terminated_jobs
            FROM tickets
        """)
        
        overall_stats = cursor.fetchone()
        
        # Jobs by location - using latest values
        cursor.execute("""
            SELECT 
                latest.location,
                COUNT(*) as count
            FROM (
                SELECT 
                    t.ticket_id,
                    td1.field_value as location
                FROM tickets t
                JOIN ticket_details td1 ON t.ticket_id = td1.ticket_id
                INNER JOIN (
                    SELECT ticket_id, MAX(created_at) as max_created_at
                    FROM ticket_details
                    WHERE field_name = 'location'
                    GROUP BY ticket_id
                ) td2 ON td1.ticket_id = td2.ticket_id 
                     AND td1.created_at = td2.max_created_at
                WHERE td1.field_name = 'location'
                    AND t.approval_status = 'approved'
                    AND t.status != 'terminated'
            ) latest
            GROUP BY latest.location
            ORDER BY count DESC
        """)
        
        locations = cursor.fetchall()
        
        # Recent activity (last 7 days)
        cursor.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as new_jobs
            FROM tickets
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """)
        
        recent_activity = cursor.fetchall()
        
        # Convert dates
        for activity in recent_activity:
            activity['date'] = activity['date'].isoformat()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'overall': overall_stats,
                'by_location': locations,
                'recent_activity': recent_activity
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_statistics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/hr/stats', methods=['GET'])
@require_jwt_auth
def get_hr_statistics():
    """Get hiring statistics and analytics for authenticated HR user"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get user info from JWT token
        auth_header = request.headers.get('Authorization')
        token = auth_header.split(' ')[1] if auth_header and auth_header.startswith('Bearer ') else None
        
        if not token:
            return jsonify({
                'success': False,
                'error': 'No token provided'
            }), 401
        
        try:
            payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=['HS256'])
            user_email = payload.get('email')
        except jwt.ExpiredSignatureError:
            return jsonify({
                'success': False,
                'error': 'Token expired'
            }), 401
        except jwt.InvalidTokenError:
            return jsonify({
                'success': False,
                'error': 'Invalid token'
            }), 401
        
        # User-specific statistics
        cursor.execute("""
            SELECT 
                COUNT(*) as total_tickets,
                SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) as approved_jobs,
                SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) as pending_approval,
                SUM(CASE WHEN approval_status = 'rejected' THEN 1 ELSE 0 END) as rejected_jobs,
                SUM(CASE WHEN status = 'terminated' THEN 1 ELSE 0 END) as terminated_jobs
            FROM tickets
            WHERE sender = %s OR user_id IN (
                SELECT user_id FROM users WHERE email = %s
            )
        """, (user_email, user_email))
        
        overall_stats = cursor.fetchone()
        
        # User-specific jobs by location
        cursor.execute("""
            SELECT 
                latest.location,
                COUNT(*) as count
            FROM (
                SELECT 
                    t.ticket_id,
                    td1.field_value as location
                FROM tickets t
                JOIN ticket_details td1 ON t.ticket_id = td1.ticket_id
                INNER JOIN (
                    SELECT ticket_id, MAX(created_at) as max_created_at
                    FROM ticket_details
                    WHERE field_name = 'location'
                    GROUP BY ticket_id
                ) td2 ON td1.ticket_id = td2.ticket_id 
                     AND td1.created_at = td2.max_created_at
                WHERE td1.field_name = 'location'
                    AND t.approval_status = 'approved'
                    AND t.status != 'terminated'
                    AND (t.sender = %s OR t.user_id IN (
                        SELECT user_id FROM users WHERE email = %s
                    ))
            ) latest
            GROUP BY latest.location
            ORDER BY count DESC
        """, (user_email, user_email))
        
        locations = cursor.fetchall()
        
        # User-specific recent activity (last 7 days)
        cursor.execute("""
            SELECT 
                DATE(created_at) as date,
                COUNT(*) as new_jobs
            FROM tickets
            WHERE created_at >= DATE_SUB(CURDATE(), INTERVAL 7 DAY)
                AND (sender = %s OR user_id IN (
                    SELECT user_id FROM users WHERE email = %s
                ))
            GROUP BY DATE(created_at)
            ORDER BY date DESC
        """, (user_email, user_email))
        
        recent_activity = cursor.fetchall()
        
        # Convert dates
        for activity in recent_activity:
            activity['date'] = activity['date'].isoformat()
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'overall': overall_stats,
                'by_location': locations,
                'recent_activity': recent_activity
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_hr_statistics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/locations', methods=['GET'])
@require_api_key
def get_locations():
    """Get list of all unique locations using latest values"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT DISTINCT td1.field_value
            FROM ticket_details td1
            INNER JOIN (
                SELECT ticket_id, MAX(created_at) as max_created_at
                FROM ticket_details
                WHERE field_name = 'location'
                GROUP BY ticket_id
            ) td2 ON td1.ticket_id = td2.ticket_id 
                 AND td1.created_at = td2.max_created_at
            JOIN tickets t ON td1.ticket_id = t.ticket_id
            WHERE td1.field_name = 'location'
                AND td1.field_value IS NOT NULL
                AND td1.field_value != 'NOT_FOUND'
                AND t.approval_status = 'approved'
            ORDER BY td1.field_value
        """)
        
        locations = [row[0] for row in cursor.fetchall()]
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'locations': locations
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_locations: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/skills', methods=['GET'])
@require_api_key
def get_skills():
    """Get list of all unique skills using latest values"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor()
        
        cursor.execute("""
            SELECT td1.field_value
            FROM ticket_details td1
            INNER JOIN (
                SELECT ticket_id, MAX(created_at) as max_created_at
                FROM ticket_details
                WHERE field_name = 'required_skills'
                GROUP BY ticket_id
            ) td2 ON td1.ticket_id = td2.ticket_id 
                 AND td1.created_at = td2.max_created_at
            JOIN tickets t ON td1.ticket_id = t.ticket_id
            WHERE td1.field_name = 'required_skills'
                AND td1.field_value IS NOT NULL
                AND td1.field_value != 'NOT_FOUND'
                AND t.approval_status = 'approved'
        """)
        
        # Extract unique skills
        all_skills = set()
        for row in cursor.fetchall():
            skills_text = row[0]
            # Split by common delimiters
            skills = re.split(r'[,;|\n]', skills_text)
            for skill in skills:
                skill = skill.strip()
                if skill:
                    all_skills.add(skill)
        
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'data': {
                'skills': sorted(list(all_skills))
            }
        })
        
    except Exception as e:
        logger.error(f"Error in get_skills: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# TICKET MANAGEMENT ENDPOINTS (for chat bot)
# ============================================

@app.route('/api/tickets/<user_id>', methods=['GET'])
def get_user_tickets(user_id):
    """Get all tickets for a user"""
    try:
        tickets = chat_bot.ticket_manager.get_user_tickets(user_id)
        
        # Format tickets for response
        formatted_tickets = []
        for ticket in tickets:
            formatted_tickets.append({
                'ticket_id': ticket['ticket_id'],
                'job_title': ticket.get('job_title', 'Untitled'),
                'status': ticket['status'],
                'approval_status': ticket['approval_status'],
                'created_at': ticket['created_at'].isoformat() if ticket.get('created_at') else None,
                'updated_at': ticket['last_updated'].isoformat() if ticket.get('last_updated') else None
            })
        
        return jsonify({
            'user_id': user_id,
            'tickets': formatted_tickets,
            'count': len(formatted_tickets)
        })
    
    except Exception as e:
        logger.error(f"Error fetching tickets: {e}")
        return jsonify({
            'error': 'Failed to fetch tickets',
            'message': str(e)
        }), 500

@app.route('/api/tickets/<ticket_id>/details', methods=['GET'])
def get_ticket_details(ticket_id):
    """Get detailed information about a specific ticket"""
    try:
        ticket = chat_bot.ticket_manager.get_ticket_details(ticket_id)
        
        if not ticket:
            return jsonify({
                'error': 'Ticket not found',
                'ticket_id': ticket_id
            }), 404
        
        # Format response
        response = {
            'ticket_id': ticket['ticket_id'],
            'status': ticket['status'],
            'approval_status': ticket['approval_status'],
            'created_at': ticket['created_at'].isoformat() if ticket.get('created_at') else None,
            'details': ticket.get('details', {})
        }
        
        return jsonify(response)
    
    except Exception as e:
        logger.error(f"Error fetching ticket details: {e}")
        return jsonify({
            'error': 'Failed to fetch ticket details',
            'message': str(e)
        }), 500

# ============================================
# WEBSOCKET EVENTS
# ============================================

@socketio.on('connect')
def handle_connect():
    """Handle WebSocket connection"""
    logger.info(f"Client connected: {request.sid}")
    emit('connected', {
        'message': 'Connected to hiring bot server',
        'features': ['chat', 'api', 'file_upload', 'resume_filtering'],
        'timestamp': datetime.now().isoformat(),
        'tunnel_url': CLOUDFLARE_TUNNEL_URL
    })

@socketio.on('disconnect')
def handle_disconnect():
    """Handle WebSocket disconnection"""
    logger.info(f"Client disconnected: {request.sid}")

@socketio.on('start_session')
def handle_start_session(data):
    """Start a new chat session via WebSocket"""
    try:
        user_id = data.get('user_id')
        result = chat_bot.start_session(user_id)
        emit('session_started', result)
    except Exception as e:
        logger.error(f"WebSocket error starting session: {e}")
        emit('error', {'error': str(e)})

@socketio.on('send_message')
def handle_websocket_message(data):
    """Handle incoming message via WebSocket"""
    try:
        session_id = data.get('session_id')
        user_id = data.get('user_id')
        message = data.get('message')
        
        if not all([session_id, user_id, message]):
            emit('error', {'error': 'Missing required fields'})
            return
        
        # Process message
        bot_response = chat_bot.process_message(session_id, user_id, message)
        
        # Format response for WebSocket
        formatted_response = {
            'response': bot_response.get('message', ''),
            'metadata': bot_response.get('metadata', {}),
            'session_id': session_id,
            'timestamp': datetime.now().isoformat()
        }
        
        emit('message_response', formatted_response)
    
    except Exception as e:
        logger.error(f"WebSocket error processing message: {e}")
        emit('error', {'error': str(e)})

# ============================================
# ERROR HANDLERS
# ============================================

@app.errorhandler(404)
def not_found(error):
    """Handle 404 errors"""
    return jsonify({
        'error': 'Not found',
        'message': 'The requested resource was not found'
    }), 404

@app.errorhandler(500)
def internal_error(error):
    """Handle 500 errors"""
    logger.error(f"Internal server error: {error}")
    return jsonify({
        'error': 'Internal server error',
        'message': 'An unexpected error occurred'
    }), 500

# ============================================
# CLEANUP HANDLER
# ============================================

def cleanup_on_exit(signum=None, frame=None):
    """Cleanup function to stop tunnel on exit"""
    print("\n🛑 Shutting down...")
    stop_cloudflare_tunnel()
    sys.exit(0)

# Register cleanup handlers
signal.signal(signal.SIGINT, cleanup_on_exit)
signal.signal(signal.SIGTERM, cleanup_on_exit)



def generate_captcha_text(length=6):
    """Generate random CAPTCHA text"""
    # Use mix of uppercase letters and numbers (avoid confusing characters)
    characters = 'ABCDEFGHJKLMNPQRSTUVWXYZ23456789'  # Removed I,O,0,1 for clarity
    return ''.join(random.choice(characters) for _ in range(length))

def create_captcha_image(text):
    """Create a CAPTCHA image with distorted text"""
    # Create image
    width = CAPTCHA_IMAGE_WIDTH
    height = CAPTCHA_IMAGE_HEIGHT
    
    # Create base image with random background color
    bg_color = (random.randint(240, 255), random.randint(240, 255), random.randint(240, 255))
    image = Image.new('RGB', (width, height), bg_color)
    draw = ImageDraw.Draw(image)
    
    # Try to use a font, fallback to default if not available
    try:
        # Try different font paths based on OS
        font_paths = [
            "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf",  # Linux
            "/System/Library/Fonts/Helvetica.ttc",  # macOS
            "C:\\Windows\\Fonts\\Arial.ttf",  # Windows
            "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",  # Alternative Linux
        ]
        
        font = None
        for font_path in font_paths:
            if os.path.exists(font_path):
                font = ImageFont.truetype(font_path, CAPTCHA_FONT_SIZE)
                break
        
        if not font:
            # Use default font if no system font found
            font = ImageFont.load_default()
    except:
        # Use default font if any error
        font = ImageFont.load_default()
    
    # Add noise lines
    for _ in range(random.randint(5, 8)):
        x1 = random.randint(0, width)
        y1 = random.randint(0, height)
        x2 = random.randint(0, width)
        y2 = random.randint(0, height)
        color = (random.randint(0, 150), random.randint(0, 150), random.randint(0, 150))
        draw.line([(x1, y1), (x2, y2)], fill=color, width=random.randint(1, 2))
    
    # Draw each character with random position and rotation
    char_spacing = width // (len(text) + 1)
    for i, char in enumerate(text):
        # Create individual character image
        char_image = Image.new('RGBA', (40, 50), (255, 255, 255, 0))
        char_draw = ImageDraw.Draw(char_image)
        
        # Random color for each character
        char_color = (
            random.randint(0, 100),
            random.randint(0, 100),
            random.randint(0, 100)
        )
        
        char_draw.text((10, 10), char, font=font, fill=char_color)
        
        # Random rotation
        angle = random.randint(-30, 30)
        char_image = char_image.rotate(angle, expand=1)
        
        # Random position
        x = char_spacing * (i + 1) - 20 + random.randint(-10, 10)
        y = (height - 40) // 2 + random.randint(-10, 10)
        
        # Paste character onto main image
        image.paste(char_image, (x, y), char_image)
    
    # Add noise dots
    for _ in range(random.randint(100, 150)):
        x = random.randint(0, width - 1)
        y = random.randint(0, height - 1)
        color = (random.randint(0, 200), random.randint(0, 200), random.randint(0, 200))
        draw.point((x, y), fill=color)
    
    # Apply slight blur for more distortion
    image = image.filter(ImageFilter.SMOOTH_MORE)
    
    return image

def generate_captcha_session():
    """Generate a new CAPTCHA and return session data"""
    captcha_text = generate_captcha_text(CAPTCHA_LENGTH)
    captcha_image = create_captcha_image(captcha_text)
    
    # Convert image to base64
    buffer = io.BytesIO()
    captcha_image.save(buffer, format='PNG')
    image_base64 = base64.b64encode(buffer.getvalue()).decode('utf-8')
    
    # Generate unique session ID
    session_id = f"captcha_{uuid.uuid4().hex}"
    
    # Store in active captchas with expiration
    active_captchas[session_id] = {
        'text': captcha_text,
        'created_at': datetime.now(),
        'attempts': 0
    }
    
    # Clean up old captchas
    cleanup_expired_captchas()
    
    logger.info(f"Generated CAPTCHA session {session_id} with text: {captcha_text}")
    
    return {
        'session_id': session_id,
        'image': f"data:image/png;base64,{image_base64}",
        'expires_in': CAPTCHA_TIMEOUT
    }

def verify_captcha(session_id, user_input):
    """Verify CAPTCHA input"""
    if not session_id or not user_input:
        return False, "Missing CAPTCHA data"
    
    if session_id not in active_captchas:
        return False, "CAPTCHA expired or invalid"
    
    captcha_data = active_captchas[session_id]
    
    # Check if expired
    if datetime.now() - captcha_data['created_at'] > timedelta(seconds=CAPTCHA_TIMEOUT):
        del active_captchas[session_id]
        return False, "CAPTCHA expired"
    
    # Check attempts
    captcha_data['attempts'] += 1
    if captcha_data['attempts'] > 3:
        del active_captchas[session_id]
        return False, "Too many failed attempts"
    
    # Verify text (case insensitive)
    if user_input.upper().strip() == captcha_data['text']:
        # Mark as verified but keep session for a short time for the actual upload
        captcha_data['verified'] = True
        captcha_data['verified_at'] = datetime.now()
        logger.info(f"CAPTCHA verified successfully for session {session_id}")
        return True, "Verified"
    
    logger.warning(f"CAPTCHA verification failed for session {session_id}. Expected: {captcha_data['text']}, Got: {user_input}")
    return False, "Incorrect CAPTCHA"
def is_captcha_verified(session_id, user_input):
    """Check if CAPTCHA session is verified and valid for use"""
    if not session_id or not user_input:
        return False, "Missing CAPTCHA data"
    
    if session_id not in active_captchas:
        return False, "CAPTCHA session not found"
    
    captcha_data = active_captchas[session_id]
    
    # Check if it was verified
    if not captcha_data.get('verified', False):
        return False, "CAPTCHA not verified"
    
    # Check if verification is still valid (allow 5 minutes after verification)
    if datetime.now() - captcha_data.get('verified_at', datetime.now()) > timedelta(minutes=5):
        del active_captchas[session_id]
        return False, "CAPTCHA verification expired"
    
    # Verify the text again for security
    if user_input.upper().strip() != captcha_data['text']:
        return False, "CAPTCHA text mismatch"
    
    # Delete session after successful use
    del active_captchas[session_id]
    logger.info(f"CAPTCHA session {session_id} used successfully for upload")
    return True, "Valid"
def cleanup_expired_captchas():
    """Remove expired CAPTCHAs from memory"""
    current_time = datetime.now()
    expired_sessions = [
        session_id for session_id, data in active_captchas.items()
        if current_time - data['created_at'] > timedelta(seconds=CAPTCHA_TIMEOUT)
    ]
    for session_id in expired_sessions:
        del active_captchas[session_id]
        logger.info(f"Cleaned up expired CAPTCHA session: {session_id}")

# ============================================
# USER AUTHENTICATION FUNCTIONS
# ============================================

def hash_password(password):
    """Hash password using SHA-256"""
    return hashlib.sha256(password.encode()).hexdigest()

def generate_jwt_token(user_id, email, role):
    """Generate JWT token for user"""
    # Use timezone.utc for compatibility with older Python versions
    from datetime import timezone
    payload = {
        'user_id': user_id,
        'email': email,
        'role': role,
        'exp': datetime.now(timezone.utc) + timedelta(hours=JWT_EXPIRATION_HOURS),
        'iat': datetime.now(timezone.utc)
    }
    return jwt.encode(payload, JWT_SECRET_KEY, algorithm=JWT_ALGORITHM)

def verify_jwt_token(token):
    """Verify JWT token and return payload"""
    try:
        payload = jwt.decode(token, JWT_SECRET_KEY, algorithms=[JWT_ALGORITHM])
        return True, payload
    except jwt.ExpiredSignatureError:
        return False, "Token expired"
    except jwt.InvalidTokenError:
        return False, "Invalid token"

def get_db_connection():
    """Get database connection"""
    try:
        conn = mysql.connector.connect(**MYSQL_CONFIG)
        return conn
    except Error as e:
        logger.error(f"Database connection error: {e}")
        return None

def create_user_table():
    """Create users table if it doesn't exist"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                role ENUM('hr') DEFAULT 'hr',  -- Only HR managers are supported
                phone VARCHAR(20),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                INDEX idx_email (email),
                INDEX idx_user_id (user_id)
            )
        """)
        conn.commit()
        cursor.close()
        conn.close()
        return True
    except Error as e:
        logger.error(f"Error creating users table: {e}")
        return False

def user_exists(email):
    """Check if user exists by email"""
    conn = get_db_connection()
    if not conn:
        return False
    
    try:
        cursor = conn.cursor()
        cursor.execute("SELECT id FROM users WHERE email = %s", (email,))
        result = cursor.fetchone()
        cursor.close()
        conn.close()
        return result is not None
    except Error as e:
        logger.error(f"Error checking user existence: {e}")
        return False

def create_user(user_data):
    """Create a new user"""
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed"
    
    try:
        cursor = conn.cursor()
        
        # Generate unique user_id
        user_id = f"user_{secrets.token_hex(8)}"
        
        # Hash password
        password_hash = hash_password(user_data['password'])
        
        cursor.execute("""
            INSERT INTO users (user_id, email, password_hash, first_name, last_name, role, phone)
            VALUES (%s, %s, %s, %s, %s, %s, %s)
        """, (
            user_id,
            user_data['email'],
            password_hash,
            user_data['first_name'],
            user_data['last_name'],
            'hr',  # Force role to be 'hr' only
            user_data.get('phone', '')
        ))
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return True, user_id
    except Error as e:
        logger.error(f"Error creating user: {e}")
        return False, str(e)

def authenticate_user(email, password):
    """Authenticate user with email and password"""
    conn = get_db_connection()
    if not conn:
        return False, "Database connection failed"
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT user_id, email, password_hash, first_name, last_name, role, is_active
            FROM users WHERE email = %s
        """, (email,))
        
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not user:
            return False, "User not found"
        
        if not user['is_active']:
            return False, "Account is deactivated"
        
        # Verify password
        if hash_password(password) != user['password_hash']:
            return False, "Invalid password"
        
        return True, user
    except Error as e:
        logger.error(f"Error authenticating user: {e}")
        return False, str(e)

def get_user_by_id(user_id):
    """Get user by user_id"""
    conn = get_db_connection()
    if not conn:
        return None
    
    try:
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT user_id, email, first_name, last_name, role, phone, created_at, is_active
            FROM users WHERE user_id = %s
        """, (user_id,))
        
        user = cursor.fetchone()
        cursor.close()
        conn.close()
        return user
    except Error as e:
        logger.error(f"Error getting user: {e}")
        return None

# ============================================
# ADD THESE API ENDPOINTS AFTER YOUR EXISTING ENDPOINTS
# ============================================

@app.route('/api/captcha/generate', methods=['GET'])
def generate_captcha():
    """Generate a new CAPTCHA"""
    try:
        captcha_data = generate_captcha_session()
        return jsonify({
            'success': True,
            'data': captcha_data
        })
    except Exception as e:
        logger.error(f"Error generating CAPTCHA: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to generate CAPTCHA'
        }), 500

@app.route('/api/captcha/verify', methods=['POST'])
def verify_captcha_endpoint():
    """Verify CAPTCHA input"""
    try:
        data = request.json
        session_id = data.get('session_id')
        user_input = data.get('captcha_text')
        
        logger.info(f"Verifying CAPTCHA for session {session_id} with input: {user_input}")
        
        is_valid, message = verify_captcha(session_id, user_input)
        
        return jsonify({
            'success': is_valid,
            'message': message
        })
    except Exception as e:
        logger.error(f"Error verifying CAPTCHA: {e}")
        return jsonify({
            'success': False,
            'error': 'Failed to verify CAPTCHA'
        }), 500

# ============================================
# TEST ENDPOINT - Create Sample Jobs
# ============================================

@app.route('/api/test/create-sample-jobs', methods=['POST'])
@require_api_key
def create_sample_jobs():
    """Create sample jobs for testing the candidate portal"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor()
        
        # Sample job data
        sample_jobs = [
            {
                'subject': 'Senior Software Engineer Position',
                'description': 'We are looking for a Senior Software Engineer to join our growing team.',
                'priority': 'medium',
                'status': 'open',
                'approval_status': 'approved',
                'job_title': 'Senior Software Engineer',
                'company_name': 'TechCorp',
                'location': 'San Francisco, CA',
                'job_type': 'Full-time',
                'salary_range': '$120,000 - $150,000',
                'job_description': 'We are looking for a Senior Software Engineer to join our growing team. You will be responsible for developing and maintaining high-quality software solutions.',
                'requirements': '5+ years of experience,Strong problem-solving skills,Experience with modern frameworks',
                'skills': 'React,Node.js,TypeScript,AWS',
                'experience_level': '5+ years'
            },
            {
                'subject': 'Product Manager Position',
                'description': 'Join our product team to help shape the future of our platform.',
                'priority': 'medium',
                'status': 'open',
                'approval_status': 'approved',
                'job_title': 'Product Manager',
                'company_name': 'InnovateTech',
                'location': 'New York, NY',
                'job_type': 'Full-time',
                'salary_range': '$100,000 - $130,000',
                'job_description': 'Join our product team to help shape the future of our platform. You will work closely with engineering and design teams.',
                'requirements': '3+ years of product management,Strong analytical skills,Excellent communication',
                'skills': 'Product Strategy,Data Analysis,User Research,Agile',
                'experience_level': '3+ years'
            },
            {
                'subject': 'UX Designer Position',
                'description': 'Create beautiful and intuitive user experiences for our web and mobile applications.',
                'priority': 'medium',
                'status': 'open',
                'approval_status': 'approved',
                'job_title': 'UX Designer',
                'company_name': 'DesignStudio',
                'location': 'Remote',
                'job_type': 'Contract',
                'salary_range': '$80,000 - $100,000',
                'job_description': 'Create beautiful and intuitive user experiences for our web and mobile applications.',
                'requirements': 'Portfolio of work,Experience with design tools,User-centered design approach',
                'skills': 'Figma,Sketch,Adobe Creative Suite,Prototyping',
                'experience_level': '2+ years'
            }
        ]
        
        created_jobs = []
        
        for job_data in sample_jobs:
            # Insert ticket
            cursor.execute("""
                INSERT INTO tickets (subject, description, priority, status, approval_status, created_at, updated_at)
                VALUES (%s, %s, %s, %s, %s, NOW(), NOW())
            """, (job_data['subject'], job_data['description'], job_data['priority'], 
                  job_data['status'], job_data['approval_status']))
            
            ticket_id = cursor.lastrowid
            
            # Insert ticket details
            details = [
                ('job_title', job_data['job_title']),
                ('company_name', job_data['company_name']),
                ('location', job_data['location']),
                ('job_type', job_data['job_type']),
                ('salary_range', job_data['salary_range']),
                ('job_description', job_data['job_description']),
                ('requirements', job_data['requirements']),
                ('skills', job_data['skills']),
                ('experience_level', job_data['experience_level'])
            ]
            
            for field_name, field_value in details:
                cursor.execute("""
                    INSERT INTO ticket_details (ticket_id, field_name, field_value, created_at)
                    VALUES (%s, %s, %s, NOW())
                """, (ticket_id, field_name, field_value))
            
            created_jobs.append({
                'ticket_id': ticket_id,
                'job_title': job_data['job_title'],
                'company_name': job_data['company_name']
            })
        
        conn.commit()
        cursor.close()
        conn.close()
        
        return jsonify({
            'success': True,
            'message': f'Successfully created {len(created_jobs)} sample jobs',
            'data': created_jobs
        })
        
    except Exception as e:
        logger.error(f"Error creating sample jobs: {str(e)}")
        return jsonify({
            'success': False,
            'error': f'Failed to create sample jobs: {str(e)}'
        }), 500

# ============================================
# MODIFY YOUR EXISTING upload_resume FUNCTION
# ============================================

# Replace your existing upload_resume function with this updated version:

@app.route('/api/tickets/<ticket_id>/resumes', methods=['POST'])
@require_api_key
def upload_resume(ticket_id):
    """Upload a resume for a specific ticket with CAPTCHA verification and email confirmation"""
    try:
        # CAPTCHA verification (existing code)
        captcha_session = request.form.get('captcha_session')
        captcha_text = request.form.get('captcha_text')
        
        logger.info(f"Resume upload attempt for ticket {ticket_id}")
        logger.info(f"CAPTCHA session: {captcha_session}, CAPTCHA text: {captcha_text}")
        
        # Verify CAPTCHA using the new method
        is_valid, message = is_captcha_verified(captcha_session, captcha_text)
        if not is_valid:
            logger.warning(f"CAPTCHA verification failed for ticket {ticket_id}: {message}")
            return jsonify({
                'success': False,
                'error': f'CAPTCHA verification failed: {message}'
            }), 400
        
        logger.info(f"CAPTCHA verified successfully for ticket {ticket_id}")
        
        # Existing database checks
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT ticket_id, subject, approval_status
            FROM tickets
            WHERE ticket_id = %s
        """, (ticket_id,))
        
        ticket = cursor.fetchone()
        
        if not ticket:
            cursor.close()
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Ticket not found'
            }), 404
        
        if ticket['approval_status'] != 'approved':
            cursor.close()
            conn.close()
            return jsonify({
                'success': False,
                'error': 'Ticket must be approved before uploading resumes'
            }), 400
        
        # Get job title from ticket details
        cursor.execute("""
            SELECT td1.field_value as job_title
            FROM ticket_details td1
            INNER JOIN (
                SELECT MAX(created_at) as max_created_at
                FROM ticket_details
                WHERE ticket_id = %s AND field_name = 'job_title'
            ) td2 ON td1.created_at = td2.max_created_at
            WHERE td1.ticket_id = %s AND td1.field_name = 'job_title'
        """, (ticket_id, ticket_id))
        
        job_result = cursor.fetchone()
        job_title = job_result['job_title'] if job_result else 'Unknown Position'
        
        cursor.close()
        conn.close()
        
        # File validation (existing code)
        if 'resume' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400
        
        file = request.files['resume']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'error': f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Get applicant details
        applicant_name = request.form.get('applicant_name', '').strip()
        applicant_email = request.form.get('applicant_email', '').strip()
        applicant_phone = request.form.get('applicant_phone', '').strip()
        cover_letter = request.form.get('cover_letter', '').strip()
        
        # Validate required fields
        if not applicant_name or not applicant_email:
            return jsonify({
                'success': False,
                'error': 'Applicant name and email are required'
            }), 400
        
        # Basic email validation
        import re
        email_pattern = r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$'
        if not re.match(email_pattern, applicant_email):
            return jsonify({
                'success': False,
                'error': 'Please provide a valid email address'
            }), 400
        
        logger.info(f"Processing resume upload for {applicant_name} ({applicant_email})")
        
        # Create folder and save resume (existing code)
        folder_path = create_ticket_folder(ticket_id, ticket['subject'])
        if not folder_path:
            return jsonify({
                'success': False,
                'error': 'Failed to create ticket folder'
            }), 500
        
        # Save the resume
        saved_path = save_resume_to_ticket(
            ticket_id, 
            file, 
            applicant_name, 
            applicant_email
        )
        
        if saved_path:
            # Generate unique application ID
            application_id = f"APP_{ticket_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}_{applicant_name.replace(' ', '').upper()[:4]}"
            
            logger.info(f"Resume uploaded successfully for ticket {ticket_id}: {saved_path}")
            
            # 🆕 SEND THANK YOU EMAIL
            try:
                send_thank_you_email_async(
                    candidate_email=applicant_email,
                    candidate_name=applicant_name,
                    job_title=job_title,
                    application_id=application_id
                )
                logger.info(f"Thank you email queued for {applicant_name} ({applicant_email})")
            except Exception as email_error:
                logger.error(f"Failed to queue thank you email: {email_error}")
                # Don't fail the upload if email fails
            
            return jsonify({
                'success': True,
                'message': 'Resume uploaded successfully! You will receive a confirmation email shortly.',
                'data': {
                    'file_path': saved_path,
                    'application_id': application_id,
                    'job_title': job_title,
                    'applicant_name': applicant_name,
                    'email_sent': EMAIL_CONFIG.get('SEND_EMAILS', True)
                }
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save resume'
            }), 500
            
    except Exception as e:
        logger.error(f"Error uploading resume: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ADDITIONAL EMAIL ENDPOINTS (OPTIONAL)
# ============================================

@app.route('/api/email/test', methods=['POST'])
@require_api_key
def test_email_configuration():
    """Test email configuration"""
    try:
        data = request.json
        test_email = data.get('test_email', EMAIL_CONFIG.get('HR_EMAIL'))
        
        if not test_email:
            return jsonify({
                'success': False,
                'error': 'Test email address required'
            }), 400
        
        # Send test email
        subject = "Email Configuration Test - HR System"
        html_content = """
        <h2>Email Test Successful! ✅</h2>
        <p>Your email configuration is working correctly.</p>
        <p>The candidate confirmation emails will be sent successfully.</p>
        <p><strong>Test Time:</strong> {}</p>
        """.format(datetime.now().strftime('%Y-%m-%d %H:%M:%S'))
        
        text_content = f"""
        Email Test Successful!
        
        Your email configuration is working correctly.
        The candidate confirmation emails will be sent successfully.
        
        Test Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}
        """
        
        success, message = send_email(test_email, subject, html_content, text_content)
        
        return jsonify({
            'success': success,
            'message': message,
            'test_email': test_email,
            'smtp_server': EMAIL_CONFIG['SMTP_SERVER'],
            'from_email': EMAIL_CONFIG['EMAIL_ADDRESS']
        })
        
    except Exception as e:
        logger.error(f"Email test failed: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/email/status', methods=['GET'])
@require_api_key
def get_email_status():
    """Get email configuration status"""
    return jsonify({
        'success': True,
        'data': {
            'email_enabled': EMAIL_CONFIG.get('SEND_EMAILS', True),
            'smtp_server': EMAIL_CONFIG['SMTP_SERVER'],
            'smtp_port': EMAIL_CONFIG['SMTP_PORT'],
            'from_email': EMAIL_CONFIG['EMAIL_ADDRESS'],
            'from_name': EMAIL_CONFIG['FROM_NAME'],
            'company_name': EMAIL_CONFIG['COMPANY_NAME'],
            'hr_email': EMAIL_CONFIG['HR_EMAIL'],
            'use_tls': EMAIL_CONFIG.get('USE_TLS', True)
        }
    })

    """Upload a resume for a specific ticket with CAPTCHA verification"""
    try:
        # CAPTCHA verification
        captcha_session = request.form.get('captcha_session')
        captcha_text = request.form.get('captcha_text')
        
        logger.info(f"Resume upload attempt for ticket {ticket_id}")
        logger.info(f"CAPTCHA session: {captcha_session}, CAPTCHA text: {captcha_text}")
        
        # Verify CAPTCHA using the new method
        is_valid, message = is_captcha_verified(captcha_session, captcha_text)
        if not is_valid:
            logger.warning(f"CAPTCHA verification failed for ticket {ticket_id}: {message}")
            return jsonify({
                'success': False,
                'error': f'CAPTCHA verification failed: {message}'
            }), 400
        
        logger.info(f"CAPTCHA verified successfully for ticket {ticket_id}")
        
        # Rest of your existing upload_resume code...
        # Check if the ticket exists and is approved
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT ticket_id, subject, approval_status
            FROM tickets
            WHERE ticket_id = %s
        """, (ticket_id,))
        
        ticket = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not ticket:
            return jsonify({
                'success': False,
                'error': 'Ticket not found'
            }), 404
        
        if ticket['approval_status'] != 'approved':
            return jsonify({
                'success': False,
                'error': 'Ticket must be approved before uploading resumes'
            }), 400
        
        # Check if file is in request
        if 'resume' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400
        
        file = request.files['resume']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'error': f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Get applicant details from form data
        applicant_name = request.form.get('applicant_name')
        applicant_email = request.form.get('applicant_email')
        
        logger.info(f"Processing resume upload for {applicant_name} ({applicant_email})")
        
        # Ensure folder exists
        folder_path = create_ticket_folder(ticket_id, ticket['subject'])
        if not folder_path:
            return jsonify({
                'success': False,
                'error': 'Failed to create ticket folder'
            }), 500
        
        # Save the resume
        saved_path = save_resume_to_ticket(
            ticket_id, 
            file, 
            applicant_name, 
            applicant_email
        )
        
        if saved_path:
            logger.info(f"Resume uploaded successfully for ticket {ticket_id}: {saved_path}")
            return jsonify({
                'success': True,
                'message': 'Resume uploaded successfully',
                'file_path': saved_path
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save resume'
            }), 500
            
    except Exception as e:
        logger.error(f"Error uploading resume: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500
    """Upload a resume for a specific ticket with CAPTCHA verification"""
    try:
        # CAPTCHA verification
        captcha_session = request.form.get('captcha_session')
        captcha_text = request.form.get('captcha_text')
        
        logger.info(f"Resume upload attempt for ticket {ticket_id}")
        logger.info(f"CAPTCHA session: {captcha_session}, CAPTCHA text: {captcha_text}")
        
        # Verify CAPTCHA using the new method
        is_valid, message = is_captcha_verified(captcha_session, captcha_text)
        if not is_valid:
            logger.warning(f"CAPTCHA verification failed for ticket {ticket_id}: {message}")
            return jsonify({
                'success': False,
                'error': f'CAPTCHA verification failed: {message}'
            }), 400
        
        logger.info(f"CAPTCHA verified successfully for ticket {ticket_id}")
        
        # Check if the ticket exists and is approved
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        cursor.execute("""
            SELECT ticket_id, subject, approval_status
            FROM tickets
            WHERE ticket_id = %s
        """, (ticket_id,))
        
        ticket = cursor.fetchone()
        cursor.close()
        conn.close()
        
        if not ticket:
            return jsonify({
                'success': False,
                'error': 'Ticket not found'
            }), 404
        
        if ticket['approval_status'] != 'approved':
            return jsonify({
                'success': False,
                'error': 'Ticket must be approved before uploading resumes'
            }), 400
        
        # Check if file is in request
        if 'resume' not in request.files:
            return jsonify({
                'success': False,
                'error': 'No file uploaded'
            }), 400
        
        file = request.files['resume']
        
        if file.filename == '':
            return jsonify({
                'success': False,
                'error': 'No file selected'
            }), 400
        
        if not allowed_file(file.filename):
            return jsonify({
                'success': False,
                'error': f'Invalid file type. Allowed types: {", ".join(ALLOWED_EXTENSIONS)}'
            }), 400
        
        # Get applicant details from form data
        applicant_name = request.form.get('applicant_name')
        applicant_email = request.form.get('applicant_email')
        
        logger.info(f"Processing resume upload for {applicant_name} ({applicant_email})")
        
        # Ensure folder exists
        folder_path = create_ticket_folder(ticket_id, ticket['subject'])
        if not folder_path:
            return jsonify({
                'success': False,
                'error': 'Failed to create ticket folder'
            }), 500
        
        # Save the resume
        saved_path = save_resume_to_ticket(
            ticket_id, 
            file, 
            applicant_name, 
            applicant_email
        )
        
        if saved_path:
            logger.info(f"Resume uploaded successfully for ticket {ticket_id}: {saved_path}")
            return jsonify({
                'success': True,
                'message': 'Resume uploaded successfully',
                'file_path': saved_path
            })
        else:
            return jsonify({
                'success': False,
                'error': 'Failed to save resume'
            }), 500
            
    except Exception as e:
        logger.error(f"Error uploading resume: {e}")
        import traceback
        traceback.print_exc()
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# ADD THIS DIAGNOSTIC ENDPOINT (OPTIONAL)
# ============================================

@app.route('/api/captcha/status', methods=['GET'])
def get_captcha_status():
    """Get CAPTCHA system status (for debugging)"""
    try:
        # Clean up expired captchas first
        cleanup_expired_captchas()
        
        return jsonify({
            'success': True,
            'data': {
                'active_sessions': len(active_captchas),
                'captcha_length': CAPTCHA_LENGTH,
                'timeout_seconds': CAPTCHA_TIMEOUT,
                'image_dimensions': f"{CAPTCHA_IMAGE_WIDTH}x{CAPTCHA_IMAGE_HEIGHT}",
                'pil_version': Image.__version__ if hasattr(Image, '__version__') else 'Unknown'
            }
        })
    except Exception as e:
        logger.error(f"Error getting CAPTCHA status: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# AUTHENTICATION API ENDPOINTS
# ============================================

@app.route('/api/auth/signup', methods=['POST'])
def signup():
    """User registration endpoint"""
    try:
        data = request.json
        required_fields = ['email', 'password', 'first_name', 'last_name']
        
        # Validate required fields
        for field in required_fields:
            if not data.get(field):
                return jsonify({
                    'success': False,
                    'error': f'Missing required field: {field}'
                }), 400
        
        # Validate email format
        email = data['email'].lower().strip()
        if not re.match(r'^[a-zA-Z0-9._%+-]+@[a-zA-Z0-9.-]+\.[a-zA-Z]{2,}$', email):
            return jsonify({
                'success': False,
                'error': 'Invalid email format'
            }), 400
        
        # Validate password strength
        password = data['password']
        if len(password) < 8:
            return jsonify({
                'success': False,
                'error': 'Password must be at least 8 characters long'
            }), 400
        
        # Check if user already exists
        if user_exists(email):
            return jsonify({
                'success': False,
                'error': 'User with this email already exists'
            }), 409
        
        # Force role to be 'hr' (only HR managers can be created)
        data['role'] = 'hr'
        
        # Create user
        success, result = create_user(data)
        if not success:
            return jsonify({
                'success': False,
                'error': result
            }), 500
        
        # Generate JWT token
        token = generate_jwt_token(result, email, 'hr')
        
        return jsonify({
            'success': True,
            'message': 'HR Manager registered successfully',
            'data': {
                'user_id': result,
                'email': email,
                'first_name': data['first_name'],
                'last_name': data['last_name'],
                'role': 'hr',
                'token': token
            }
        }), 201
        
    except Exception as e:
        logger.error(f"Error in signup: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/api/auth/login', methods=['POST'])
def login():
    """User login endpoint"""
    try:
        data = request.json
        
        if not data.get('email') or not data.get('password'):
            return jsonify({
                'success': False,
                'error': 'Email and password are required'
            }), 400
        
        email = data['email'].lower().strip()
        password = data['password']
        
        # Authenticate user
        success, result = authenticate_user(email, password)
        if not success:
            return jsonify({
                'success': False,
                'error': result
            }), 401
        
        # Check if user is HR manager (only HR managers can login)
        if result['role'] != 'hr':
            return jsonify({
                'success': False,
                'error': 'Access denied. Only HR managers can login to this system.'
            }), 403
        
        # Generate JWT token
        token = generate_jwt_token(result['user_id'], result['email'], result['role'])
        
        return jsonify({
            'success': True,
            'message': 'Login successful',
            'data': {
                'user_id': result['user_id'],
                'email': result['email'],
                'first_name': result['first_name'],
                'last_name': result['last_name'],
                'role': result['role'],
                'token': token
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error in login: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/api/auth/profile', methods=['GET'])
def get_profile():
    """Get user profile (requires authentication)"""
    try:
        # Get token from Authorization header
        auth_header = request.headers.get('Authorization')
        if not auth_header or not auth_header.startswith('Bearer '):
            return jsonify({
                'success': False,
                'error': 'Authorization header required'
            }), 401
        
        token = auth_header.split(' ')[1]
        
        # Verify token
        is_valid, payload = verify_jwt_token(token)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': payload
            }), 401
        
        # Get user data
        user = get_user_by_id(payload['user_id'])
        if not user:
            return jsonify({
                'success': False,
                'error': 'User not found'
            }), 404
        
        return jsonify({
            'success': True,
            'data': {
                'user_id': user['user_id'],
                'email': user['email'],
                'first_name': user['first_name'],
                'last_name': user['last_name'],
                'role': user['role'],
                'phone': user['phone'],
                'created_at': user['created_at'].isoformat() if user['created_at'] else None
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error getting profile: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

@app.route('/api/auth/verify', methods=['POST'])
def verify_token():
    """Verify JWT token validity"""
    try:
        data = request.json
        token = data.get('token')
        
        if not token:
            return jsonify({
                'success': False,
                'error': 'Token is required'
            }), 400
        
        # Verify token
        is_valid, payload = verify_jwt_token(token)
        if not is_valid:
            return jsonify({
                'success': False,
                'error': payload
            }), 401
        
        return jsonify({
            'success': True,
            'data': {
                'user_id': payload['user_id'],
                'email': payload['email'],
                'role': payload['role'],
                'exp': payload['exp']
            }
        }), 200
        
    except Exception as e:
        logger.error(f"Error verifying token: {e}")
        return jsonify({
            'success': False,
            'error': 'Internal server error'
        }), 500

# ============================================
# NEW ENDPOINTS FOR FOLDER MANAGEMENT
# ============================================

@app.route('/api/jobs/<ticket_id>/folder-info', methods=['GET'])
@require_api_key
def get_job_folder_information(ticket_id):
    """Get detailed information about a job's folder"""
    try:
        folder_info = get_job_folder_info(ticket_id)
        
        return jsonify({
            'success': True,
            'data': folder_info
        })
        
    except Exception as e:
        logger.error(f"Error getting folder info: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/maintenance/auto-create-folders', methods=['POST'])
@require_api_key
def auto_create_folders_endpoint():
    """Automatically create folders for all tickets that need them"""
    try:
        auto_create_folders_for_pending_tickets()
        
        return jsonify({
            'success': True,
            'message': 'Auto folder creation completed successfully'
        })
        
    except Exception as e:
        logger.error(f"Error in auto create folders endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/maintenance/cleanup-folders', methods=['POST'])
@require_api_key
def cleanup_folders_endpoint():
    """Clean up orphaned folders"""
    try:
        cleanup_orphaned_folders()
        
        return jsonify({
            'success': True,
            'message': 'Folder cleanup completed successfully'
        })
        
    except Exception as e:
        logger.error(f"Error in cleanup folders endpoint: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

@app.route('/api/maintenance/folder-stats', methods=['GET'])
@require_api_key
def get_folder_statistics():
    """Get statistics about job folders"""
    try:
        conn = get_db_connection()
        if not conn:
            return jsonify({
                'success': False,
                'error': 'Database connection failed'
            }), 500
        
        cursor = conn.cursor(dictionary=True)
        
        # Get total approved jobs
        cursor.execute("""
            SELECT COUNT(*) as total_approved
            FROM tickets
            WHERE approval_status = 'approved'
        """)
        total_approved = cursor.fetchone()['total_approved']
        
        cursor.close()
        conn.close()
        
        # Count actual folders
        actual_folders = len([f for f in os.listdir(BASE_STORAGE_PATH) 
                            if not f.startswith(('.', 'batch_results'))])
        
        # Count total resumes
        total_resumes = 0
        for folder_name in os.listdir(BASE_STORAGE_PATH):
            if folder_name.startswith(('.', 'batch_results')):
                continue
            folder_path = os.path.join(BASE_STORAGE_PATH, folder_name)
            if os.path.isdir(folder_path):
                resume_files = [f for f in os.listdir(folder_path) 
                               if f.lower().endswith(('.pdf', '.doc', '.docx', '.txt'))]
                total_resumes += len(resume_files)
        
        return jsonify({
            'success': True,
            'data': {
                'total_approved_jobs': total_approved,
                'jobs_with_folders': actual_folders,
                'folder_coverage': f"{(actual_folders/total_approved*100):.1f}%" if total_approved > 0 else "0%",
                'total_resumes': total_resumes,
                'average_resumes_per_job': f"{total_resumes/actual_folders:.1f}" if actual_folders > 0 else "0",
                'storage_path': BASE_STORAGE_PATH
            }
        })
        
    except Exception as e:
        logger.error(f"Error getting folder statistics: {e}")
        return jsonify({
            'success': False,
            'error': str(e)
        }), 500

# ============================================
# MAIN EXECUTION
# ============================================

def main():
    """Run the complete server"""
    # Get local IP address
    hostname = socket.gethostname()
    local_ip = socket.gethostbyname(hostname)
    
    print("="*80)
    print("🚀 COMPLETE HIRING BOT SERVER - CHAT + API + CLOUDFLARE TUNNEL + AI FILTERING")
    print("="*80)
    print(f"Database: {MYSQL_CONFIG['database']}@{MYSQL_CONFIG['host']}")
    print(f"Local URL: http://localhost:{API_PORT}")
    print(f"Network URL: http://{local_ip}:{API_PORT}")
    print(f"API Key: {API_KEY}")
    print(f"Storage Path: {BASE_STORAGE_PATH}")
    print("="*80)
    
    # Create folders for existing approved tickets
    create_folders_for_existing_approved_tickets()
    
    # Auto-create folders for any pending tickets that need them
    auto_create_folders_for_pending_tickets()
    
    # Create users table for authentication
    if create_user_table():
        print("✅ User authentication system initialized")
    else:
        print("❌ Failed to initialize user authentication system")
    
    # Start Cloudflare tunnel
    tunnel_url = start_cloudflare_tunnel()
    
    if tunnel_url:
        print("\n📱 Your complete system is accessible globally!")
        print(f"   Public URL: {tunnel_url}")
        print(f"\n🔗 For React Frontend:")
        print(f"   const API_BASE_URL = '{tunnel_url}';")
        print(f"\n🔐 Example API calls:")
        print(f"   # Chat Interface:")
        print(f"   {tunnel_url}")
        print(f"\n   # Get approved jobs:")
        print(f"   curl -H 'X-API-Key: {API_KEY}' {tunnel_url}/api/jobs/approved")
        print(f"\n   # Trigger AI filtering:")
        print(f"   curl -X POST -H 'X-API-Key: {API_KEY}' {tunnel_url}/api/tickets/TICKET_ID/filter-resumes")
        print(f"\n   # Get top resumes:")
        print(f"   curl -H 'X-API-Key: {API_KEY}' {tunnel_url}/api/tickets/TICKET_ID/top-resumes")
        print(f"\n   # Upload resume:")
        print(f"   curl -X POST -H 'X-API-Key: {API_KEY}' \\")
        print(f"        -F 'resume=@resume.pdf' \\")
        print(f"        -F 'applicant_name=John Doe' \\")
        print(f"        -F 'applicant_email=john@example.com' \\")
        print(f"        {tunnel_url}/api/tickets/TICKET_ID/resumes")
    else:
        print("\n⚠️  Running in local mode only")
        print("   Install cloudflared for public access")
    
    print("\n📚 Features:")
    print("  ✅ Chat Bot - AI-powered job posting assistant")
    print("  ✅ Job Management API - Full REST API")
    print("  ✅ Resume Management - Upload and organize resumes")
    print("  ✅ AI Resume Filtering - Automated candidate ranking")
    print("  ✅ Background Processing - Non-blocking filtering")
    print("  ✅ WebSocket Support - Real-time communication")
    print("  ✅ Cloudflare Tunnel - Global accessibility")
    
    print("\n📚 API Endpoints:")
    print("\n🔹 Chat:")
    print("  POST /api/chat/start")
    print("  POST /api/chat/message")
    print("  GET  /api/chat/history/<id>")
    
    print("\n🔹 Job Management:")
    print("  GET  /api/jobs/approved")
    print("  GET  /api/jobs/<id>")
    print("  GET  /api/jobs/search?q=<query>")
    print("  GET  /api/stats")
    print("  GET  /api/locations")
    print("  GET  /api/skills")
    
    print("\n🔹 Resume Management:")
    print("  POST /api/tickets/<id>/approve")
    print("  POST /api/tickets/<id>/resumes")
    print("  GET  /api/tickets/<id>/resumes")
    print("  GET  /api/tickets/<id>/resumes/<filename>")
    
    print("\n🔹 Folder Management:")
    print("  GET  /api/jobs/<id>/folder-info")
    print("  POST /api/maintenance/auto-create-folders")
    print("  POST /api/maintenance/cleanup-folders")
    print("  GET  /api/maintenance/folder-stats")
    
    print("\n🔹 AI Resume Filtering:")
    print("  GET  /api/tickets/<id>/filtering-status")
    print("  POST /api/tickets/<id>/filter-resumes")
    print("  GET  /api/tickets/<id>/top-resumes")
    print("  GET  /api/tickets/<id>/filtering-report")
    print("  POST /api/tickets/<id>/send-top-resumes")
    
    print("\n✋ Press CTRL+C to stop the server")
    print("="*80 + "\n")
    
    try:
        # Run with SocketIO for WebSocket support
        socketio.run(app, host='0.0.0.0', port=API_PORT, debug=False)
    except KeyboardInterrupt:
        cleanup_on_exit()
    except Exception as e:
        print(f"❌ Server error: {e}")
        cleanup_on_exit()

if __name__ == '__main__':
    main()