#!/usr/bin/env python3
"""
Email Hiring Bot using AutoGen Framework with OpenAI API and MySQL Database
Multi-agent system for processing hiring emails with ticket management
ENHANCED: Includes conversational AI support for natural language interactions
FIXED: Proper approval handling to prevent accidental rejections
FIXED: Better classification of update emails after approval
"""

import imaplib
import email
import os
import smtplib
from email.message import EmailMessage
import tempfile
import sys
import re
import json
from datetime import datetime
import hashlib
from typing import Dict, List, Tuple, Optional, Any
import autogen
from autogen import AssistantAgent, UserProxyAgent, ConversableAgent, GroupChat, GroupChatManager
import logging
import requests
import secrets
import string
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
from dotenv import load_dotenv
import uuid

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION - LOADED FROM ENVIRONMENT VARIABLES
# ============================================================================

# EMAIL CREDENTIALS
EMAIL_ADDRESS = os.getenv("EMAIL_ADDRESS", "fardeen78754@gmail.com")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD")

# OPENAI API CONFIGURATION
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
OPENAI_API_BASE = "https://api.openai.com/v1"

# MySQL DATABASE CONFIGURATION
MYSQL_CONFIG = {
    'host': os.getenv("MYSQL_HOST", "localhost"),
    'user': os.getenv("MYSQL_USER", "root"),
    'password': os.getenv("MYSQL_PASSWORD"),
    'database': os.getenv("MYSQL_DATABASE", "hiring_bot"),
}

# Validate required environment variables
if not OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables!")
if not EMAIL_PASSWORD:
    raise ValueError("EMAIL_PASSWORD not found in environment variables!")

# Validate MySQL password
if not MYSQL_CONFIG.get('password'):
    raise ValueError("MYSQL_PASSWORD not found in environment variables!")

# EMAIL SERVER SETTINGS
IMAP_SERVER = "imap.gmail.com"
SMTP_SERVER = "smtp.gmail.com"
SMTP_PORT = 587

# PROCESSING SETTINGS
MAX_EMAILS_TO_PROCESS = int(os.getenv("MAX_EMAILS_TO_PROCESS", "10"))
PROCESS_ONLY_HIRING_EMAILS = os.getenv("PROCESS_ONLY_HIRING_EMAILS", "True").lower() == "true"

# AutoGen Configuration
config_list = [
    {
        "model": OPENAI_MODEL,
        "api_key": OPENAI_API_KEY,
        "base_url": OPENAI_API_BASE,
        "api_type": "openai",
    }
]

llm_config = {
    "config_list": config_list,
    "temperature": 0.1,
    "seed": 42,
    "cache_seed": None,
    "timeout": 120,
    "max_tokens": 500,
}

# Required details
REQUIRED_HIRING_DETAILS = [
    "job_title", "location", "experience_required", "salary_range",
    "job_description", "required_skills", "employment_type", "deadline"
]

# ============================================================================
# UNIFIED DATABASE SETUP (SHARED WITH CHAT BOT)
# ============================================================================

class DatabaseManager:
    """Manages MySQL database connections and operations"""
    
    def __init__(self, config: Dict[str, Any]):
        self.config = config
        self.setup_database()
    
    @contextmanager
    def get_connection(self):
        """Context manager for database connections"""
        conn = None
        try:
            conn = mysql.connector.connect(**self.config)
            yield conn
        except Error as e:
            logger.error(f"Database error: {e}")
            if conn:
                conn.rollback()
            raise
        finally:
            if conn and conn.is_connected():
                conn.close()
    
    def setup_database(self):
        """Create database and tables if they don't exist"""
        config_without_db = self.config.copy()
        db_name = config_without_db.pop('database')
        
        try:
            conn = mysql.connector.connect(**config_without_db)
            cursor = conn.cursor()
            
            # Create database if it doesn't exist
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
            cursor.execute(f"USE {db_name}")
            
            # Create unified tickets table (shared with chat bot)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS tickets (
                    ticket_id VARCHAR(10) PRIMARY KEY,
                    source ENUM('email', 'chat') DEFAULT 'email',
                    sender VARCHAR(255) NOT NULL,
                    user_id VARCHAR(255),
                    subject TEXT,
                    session_id VARCHAR(36),
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    status VARCHAR(50) DEFAULT 'new',
                    approval_status VARCHAR(50) DEFAULT 'pending',
                    approved BOOLEAN DEFAULT FALSE,
                    approved_at DATETIME,
                    approval_token VARCHAR(32),
                    terminated_at DATETIME,
                    terminated_by VARCHAR(255),
                    termination_reason TEXT,
                    rejected_at DATETIME,
                    rejection_reason TEXT,
                    INDEX idx_sender (sender),
                    INDEX idx_user_id (user_id),
                    INDEX idx_status (status),
                    INDEX idx_approval_status (approval_status),
                    INDEX idx_source (source)
                )
            """)
            
            # Create ticket_details table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_details (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ticket_id VARCHAR(10) NOT NULL,
                    field_name VARCHAR(100) NOT NULL,
                    field_value TEXT,
                    is_initial BOOLEAN DEFAULT TRUE,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source ENUM('email', 'chat') DEFAULT 'email',
                    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    INDEX idx_ticket_field (ticket_id, field_name)
                )
            """)
            
            # Create ticket_updates table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_updates (
                    id INT AUTO_INCREMENT PRIMARY KEY,
                    ticket_id VARCHAR(10) NOT NULL,
                    update_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    updated_fields JSON,
                    update_source ENUM('email', 'chat') DEFAULT 'email',
                    updated_after_approval BOOLEAN DEFAULT FALSE,
                    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    INDEX idx_ticket_updates (ticket_id)
                )
            """)
            
            # Add the updated_after_approval column if it doesn't exist
            cursor.execute("""
                SELECT COLUMN_NAME 
                FROM INFORMATION_SCHEMA.COLUMNS 
                WHERE TABLE_SCHEMA = %s 
                AND TABLE_NAME = 'ticket_updates' 
                AND COLUMN_NAME = 'updated_after_approval'
            """, (db_name,))
            
            if not cursor.fetchone():
                cursor.execute("""
                    ALTER TABLE ticket_updates 
                    ADD COLUMN updated_after_approval BOOLEAN DEFAULT FALSE
                """)
                logger.info("Added updated_after_approval column to ticket_updates table")
            
            # Create pending_approvals table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS pending_approvals (
                    approval_token VARCHAR(32) PRIMARY KEY,
                    ticket_id VARCHAR(10) NOT NULL,
                    hr_email VARCHAR(255) NOT NULL,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    status VARCHAR(50) DEFAULT 'pending',
                    approved_at DATETIME,
                    rejected_at DATETIME,
                    rejection_reason TEXT,
                    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    INDEX idx_ticket_approval (ticket_id),
                    INDEX idx_status_approval (status)
                )
            """)
            
            # Create sessions table (for both email and chat)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_sessions (
                    session_id VARCHAR(36) PRIMARY KEY,
                    session_type ENUM('email', 'chat') DEFAULT 'chat',
                    user_id VARCHAR(255),
                    user_email VARCHAR(255),
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_activity DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    status VARCHAR(50) DEFAULT 'active',
                    INDEX idx_user_id (user_id),
                    INDEX idx_user_email (user_email),
                    INDEX idx_last_activity (last_activity)
                )
            """)
            
            # Create messages table (for both systems)
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS chat_messages (
                    message_id INT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    sender_type ENUM('user', 'assistant', 'system') NOT NULL,
                    message_content TEXT NOT NULL,
                    message_metadata JSON,
                    timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    source ENUM('email', 'chat') DEFAULT 'chat',
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                    INDEX idx_session_messages (session_id, timestamp)
                )
            """)
            
            # Create conversation_context table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_context (
                    context_id INT AUTO_INCREMENT PRIMARY KEY,
                    session_id VARCHAR(36) NOT NULL,
                    context_type VARCHAR(50) NOT NULL,
                    context_data JSON,
                    created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    FOREIGN KEY (session_id) REFERENCES chat_sessions(session_id) ON DELETE CASCADE,
                    INDEX idx_session_context (session_id)
                )
            """)
            
            # Create ticket history table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS ticket_history (
                    history_id INT AUTO_INCREMENT PRIMARY KEY,
                    ticket_id VARCHAR(10) NOT NULL,
                    field_name VARCHAR(100) NOT NULL,
                    old_value TEXT,
                    new_value TEXT,
                    changed_by VARCHAR(255),
                    changed_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    change_type ENUM('create', 'update', 'terminate') DEFAULT 'update',
                    source ENUM('email', 'chat') DEFAULT 'email',
                    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    INDEX idx_ticket_history (ticket_id, changed_at)
                )
            """)
            
            # Create conversations table for email conversations
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversations (
                    conversation_id VARCHAR(32) PRIMARY KEY,
                    user_email VARCHAR(255) NOT NULL,
                    started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                    last_message_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                    message_count INT DEFAULT 0,
                    status VARCHAR(50) DEFAULT 'active',
                    INDEX idx_user_email (user_email),
                    INDEX idx_last_message (last_message_at)
                )
            """)
            
            # Create conversation messages table
            cursor.execute("""
                CREATE TABLE IF NOT EXISTS conversation_messages (
                    message_id INT AUTO_INCREMENT PRIMARY KEY,
                    conversation_id VARCHAR(32) NOT NULL,
                    sender_type ENUM('user', 'assistant') NOT NULL,
                    message_content TEXT NOT NULL,
                    message_timestamp DATETIME DEFAULT CURRENT_TIMESTAMP,
                    intent VARCHAR(50),
                    sentiment VARCHAR(20),
                    FOREIGN KEY (conversation_id) REFERENCES conversations(conversation_id) ON DELETE CASCADE,
                    INDEX idx_conversation_messages (conversation_id, message_timestamp)
                )
            """)
            
            conn.commit()
            logger.info("Database and tables created successfully")
            
        except Error as e:
            logger.error(f"Error setting up database: {e}")
            raise
        finally:
            if conn and conn.is_connected():
                cursor.close()
                conn.close()

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_json_from_text(text):
    """Extract JSON from text that might contain markdown code blocks"""
    if not isinstance(text, str):
        return None
    
    try:
        return json.loads(text.strip())
    except:
        pass
    
    if '```' in text:
        parts = text.split('```')
        for i in range(1, len(parts), 2):
            content = parts[i]
            lines = content.split('\n')
            if lines and lines[0].strip() in ['json', 'JSON', '']:
                content = '\n'.join(lines[1:])
            try:
                return json.loads(content.strip())
            except:
                continue
    
    start = text.find('{')
    end = text.rfind('}')
    if start >= 0 and end > start:
        try:
            return json.loads(text[start:end+1])
        except:
            pass
    
    return None

def clean_response_text(text):
    """Remove code blocks and clean response text"""
    if not isinstance(text, str):
        return str(text) if text else ""
    
    if '```' in text:
        parts = text.split('```')
        cleaned = ''.join(parts[i] for i in range(0, len(parts), 2))
        text = cleaned.strip()
    
    if text.strip().startswith('{') and text.strip().endswith('}'):
        try:
            json_data = json.loads(text)
            if 'message' in json_data:
                text = json_data['message']
            elif 'content' in json_data:
                text = json_data['content']
            elif 'response' in json_data:
                text = json_data['response']
            else:
                text = str(json_data)
        except:
            pass
    
    return text.strip()

# ============================================================================
# APPROVAL MANAGER
# ============================================================================

class ApprovalManager:
    """Manages job posting approvals using MySQL"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def generate_approval_token(self) -> str:
        """Generate a unique approval token"""
        return ''.join(secrets.choice(string.ascii_letters + string.digits) for _ in range(32))
    
    def create_approval_request(self, ticket_id: str, ticket_data: Dict[str, Any], 
                              hr_email: str) -> str:
        """Create a new approval request"""
        approval_token = self.generate_approval_token()
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO pending_approvals (approval_token, ticket_id, hr_email)
                VALUES (%s, %s, %s)
            """, (approval_token, ticket_id, hr_email))
            conn.commit()
        
        logger.info(f"Created approval request with token: {approval_token}")
        return approval_token
    
    def process_approval(self, token: str) -> Tuple[bool, str, Optional[str]]:
        """Process an approval token"""
        logger.info(f"Processing approval for token: {token}")
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT ticket_id, status FROM pending_approvals 
                WHERE approval_token = %s
            """, (token,))
            
            approval = cursor.fetchone()
            
            if not approval:
                logger.warning(f"Token {token} not found in approvals")
                return False, "Invalid approval token", None
            
            if approval['status'] != 'pending':
                logger.warning(f"Approval already processed with status: {approval['status']}")
                return False, f"Approval already processed (status: {approval['status']})", approval['ticket_id']
            
            cursor.execute("""
                UPDATE pending_approvals 
                SET status = 'approved', approved_at = NOW()
                WHERE approval_token = %s
            """, (token,))
            
            conn.commit()
            
            logger.info(f"Approval processed successfully for ticket: {approval['ticket_id']}")
            return True, "Approval processed successfully", approval['ticket_id']
    
    def process_rejection(self, token: str, reason: str) -> Tuple[bool, str, Optional[str]]:
        """Process a rejection"""
        logger.info(f"Processing rejection for token: {token}")
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT ticket_id, status FROM pending_approvals 
                WHERE approval_token = %s
            """, (token,))
            
            approval = cursor.fetchone()
            
            if not approval:
                return False, "Invalid approval token", None
            
            if approval['status'] != 'pending':
                return False, f"Approval already processed (status: {approval['status']})", approval['ticket_id']
            
            cursor.execute("""
                UPDATE pending_approvals 
                SET status = 'rejected', rejected_at = NOW(), rejection_reason = %s
                WHERE approval_token = %s
            """, (reason, token))
            
            conn.commit()
            
            logger.info(f"Job posting rejected for ticket: {approval['ticket_id']}")
            return True, f"Job posting rejected: {reason}", approval['ticket_id']

# ============================================================================
# TICKET MANAGEMENT SYSTEM
# ============================================================================

class TicketManager:
    """Manages hiring tickets with MySQL persistence"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def generate_ticket_id(self, sender: str, subject: str) -> str:
        """Generate a unique ticket ID with timestamp to ensure uniqueness"""
        import time
        import random
        
        # Include timestamp and random component to ensure uniqueness
        timestamp = str(int(time.time() * 1000))
        random_part = str(random.randint(1000, 9999))
        
        # Create a hash that includes sender, subject, timestamp, and random part
        hash_input = f"{sender}_{subject}_{timestamp}_{random_part}".lower()
        return hashlib.md5(hash_input.encode()).hexdigest()[:10]
    
    def create_or_update_ticket_with_id(self, ticket_id: str, sender: str, subject: str, 
                                       details: Dict[str, str], timestamp: str) -> Tuple[str, bool, str]:
        """Update an existing ticket with a specific ticket ID"""
        logger.info(f"create_or_update_ticket_with_id called with ticket_id: {ticket_id}")
        logger.info(f"Details to save: {details}")
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT status, approval_status FROM tickets 
                WHERE ticket_id = %s
            """, (ticket_id,))
            
            existing = cursor.fetchone()
            
            if not existing:
                logger.error(f"Ticket {ticket_id} not found for update!")
                return ticket_id, False, "not_found"
            
            if existing['status'] == 'terminated':
                return ticket_id, False, "terminated"
            
            # Allow updates to approved tickets - just log a warning
            if existing['approval_status'] == 'approved':
                logger.info(f"Updating approved ticket {ticket_id} - changes will be reflected on live posting")
            
            cursor.execute("""
                UPDATE tickets 
                SET last_updated = NOW(), status = 'updated'
                WHERE ticket_id = %s
            """, (ticket_id,))
            
            # Track if this is an update after approval
            was_approved = existing['approval_status'] == 'approved'
            cursor.execute("""
                INSERT INTO ticket_updates (ticket_id, updated_fields, update_source, updated_after_approval)
                VALUES (%s, %s, 'email', %s)
            """, (ticket_id, json.dumps(details), was_approved))
            
            for field_name, field_value in details.items():
                if field_value and field_value != "NOT_FOUND":
                    cursor.execute("""
                        INSERT INTO ticket_details (ticket_id, field_name, field_value, is_initial, source)
                        VALUES (%s, %s, %s, FALSE, 'email')
                    """, (ticket_id, field_name, field_value))
                    
                    # Add to history
                    cursor.execute("""
                        INSERT INTO ticket_history (ticket_id, field_name, new_value, changed_by, change_type, source)
                        VALUES (%s, %s, %s, %s, 'update', 'email')
                    """, (ticket_id, field_name, field_value, sender))
            
            conn.commit()
            
            logger.info(f"Ticket {ticket_id} updated successfully")
            return ticket_id, True, "active"
    
    def create_or_update_ticket(self, sender: str, subject: str, details: Dict[str, str], 
                                timestamp: str) -> Tuple[str, bool, str]:
        """Create a new ticket or update existing one"""
        ticket_id = self.generate_ticket_id(sender, subject)
        
        logger.info(f"create_or_update_ticket called with ticket_id: {ticket_id}")
        logger.info(f"Details to save: {details}")
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT status, approval_status FROM tickets 
                WHERE ticket_id = %s
            """, (ticket_id,))
            
            existing = cursor.fetchone()
            
            if existing:
                if existing['status'] == 'terminated':
                    return ticket_id, False, "terminated"
                
                # Allow updates to approved tickets - just log a warning
                if existing['approval_status'] == 'approved':
                    logger.info(f"Updating approved ticket {ticket_id} - changes will be reflected on live posting")
                
                cursor.execute("""
                    UPDATE tickets 
                    SET last_updated = NOW(), status = 'updated'
                    WHERE ticket_id = %s
                """, (ticket_id,))
                
                # Track if this is an update after approval
                was_approved = existing['approval_status'] == 'approved'
                cursor.execute("""
                    INSERT INTO ticket_updates (ticket_id, updated_fields, update_source, updated_after_approval)
                    VALUES (%s, %s, 'email', %s)
                """, (ticket_id, json.dumps(details), was_approved))
                
                for field_name, field_value in details.items():
                    if field_value and field_value != "NOT_FOUND":
                        cursor.execute("""
                            INSERT INTO ticket_details (ticket_id, field_name, field_value, is_initial, source)
                            VALUES (%s, %s, %s, FALSE, 'email')
                        """, (ticket_id, field_name, field_value))
                
                is_update = True
            else:
                # Create new ticket
                cursor.execute("""
                    INSERT INTO tickets (ticket_id, source, sender, user_id, subject)
                    VALUES (%s, 'email', %s, %s, %s)
                """, (ticket_id, sender, sender, subject))
                
                for field_name, field_value in details.items():
                    if field_value and field_value != "NOT_FOUND":
                        cursor.execute("""
                            INSERT INTO ticket_details (ticket_id, field_name, field_value, is_initial, source)
                            VALUES (%s, %s, %s, TRUE, 'email')
                        """, (ticket_id, field_name, field_value))
                        
                        # Add to history
                        cursor.execute("""
                            INSERT INTO ticket_history (ticket_id, field_name, new_value, changed_by, change_type, source)
                            VALUES (%s, %s, %s, %s, 'create', 'email')
                        """, (ticket_id, field_name, field_value, sender))
                
                is_update = False
            
            conn.commit()
            
            return ticket_id, is_update, "active"
    
    def approve_ticket(self, ticket_id: str) -> bool:
        """Approve a ticket and mark it as ready for website display"""
        logger.info(f"Approving ticket: {ticket_id}")
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE tickets 
                SET approval_status = 'approved', 
                    approved = TRUE, 
                    approved_at = NOW(),
                    status = 'posted'
                WHERE ticket_id = %s
            """, (ticket_id,))
            
            affected = cursor.rowcount
            conn.commit()
            
            if affected > 0:
                logger.info(f"Ticket {ticket_id} approved and marked as posted")
                return True
            else:
                logger.error(f"Failed to approve ticket {ticket_id}")
                return False
    
    def terminate_ticket(self, ticket_id: str, terminated_by: str, reason: str = "") -> bool:
        """Terminate a ticket"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                UPDATE tickets 
                SET status = 'terminated',
                    terminated_at = NOW(),
                    terminated_by = %s,
                    termination_reason = %s,
                    approval_status = 'terminated'
                WHERE ticket_id = %s
            """, (terminated_by, reason, ticket_id))
            
            affected = cursor.rowcount
            conn.commit()
            
            return affected > 0
    
    def get_ticket_details(self, ticket_id: str) -> Optional[Dict[str, Any]]:
        """Get details of a specific ticket"""
        logger.info(f"get_ticket_details called with ticket_id: '{ticket_id}'")
        
        ticket_id = ticket_id.strip().lower()
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT * FROM tickets 
                WHERE LOWER(ticket_id) = %s
            """, (ticket_id,))
            
            ticket = cursor.fetchone()
            
            if not ticket:
                logger.warning(f"No ticket found for ID: {ticket_id}")
                return None
            
            cursor.execute("""
                SELECT field_name, field_value 
                FROM ticket_details 
                WHERE ticket_id = %s AND is_initial = TRUE
            """, (ticket['ticket_id'],))
            
            initial_details = {row['field_name']: row['field_value'] for row in cursor.fetchall()}
            
            cursor.execute("""
                SELECT update_timestamp, updated_fields 
                FROM ticket_updates 
                WHERE ticket_id = %s 
                ORDER BY update_timestamp
            """, (ticket['ticket_id'],))
            
            updates = []
            for row in cursor.fetchall():
                updates.append({
                    'timestamp': row['update_timestamp'].isoformat(),
                    'details': json.loads(row['updated_fields']) if row['updated_fields'] else {}
                })
            
            for key, value in ticket.items():
                if isinstance(value, datetime):
                    ticket[key] = value.isoformat()
            
            ticket['initial_details'] = initial_details
            ticket['updates'] = updates
            
            return ticket
    
    def get_complete_ticket_details(self, ticket_id: str) -> Dict[str, Any]:
        """Get complete ticket details including all updates"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT field_name, field_value 
                FROM ticket_details 
                WHERE ticket_id = %s 
                ORDER BY created_at DESC
            """, (ticket_id,))
            
            details = {}
            for row in cursor.fetchall():
                if row['field_name'] not in details:
                    details[row['field_name']] = row['field_value']
            
            return details
    
    def get_sender_tickets(self, sender: str) -> List[Dict[str, Any]]:
        """Get all active tickets from a sender"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT t.ticket_id, t.created_at, t.source,
                       td.field_value as job_title
                FROM tickets t
                LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                    AND td.field_name = 'job_title' AND td.is_initial = TRUE
                WHERE t.sender = %s AND t.status != 'terminated'
            """, (sender,))
            
            tickets = []
            for row in cursor.fetchall():
                tickets.append({
                    'id': row['ticket_id'],
                    'job_title': row['job_title'] or 'Unknown',
                    'created': row['created_at'].isoformat(),
                    'source': row['source']
                })
            
            return tickets

# ============================================================================
# CONVERSATION MANAGER
# ============================================================================

class ConversationManager:
    """Manages conversation history and context"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def get_or_create_conversation(self, user_email: str) -> str:
        """Get existing conversation or create new one"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                SELECT conversation_id 
                FROM conversations 
                WHERE user_email = %s 
                AND status = 'active'
                AND last_message_at > DATE_SUB(NOW(), INTERVAL 24 HOUR)
                ORDER BY last_message_at DESC
                LIMIT 1
            """, (user_email,))
            
            result = cursor.fetchone()
            
            if result:
                return result[0]
            
            conversation_id = hashlib.md5(f"{user_email}_{datetime.now()}".encode()).hexdigest()
            cursor.execute("""
                INSERT INTO conversations (conversation_id, user_email)
                VALUES (%s, %s)
            """, (conversation_id, user_email))
            conn.commit()
            
            return conversation_id
    
    def add_message(self, conversation_id: str, sender_type: str, 
                   content: str, intent: str = None, sentiment: str = None):
        """Add message to conversation history"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO conversation_messages 
                (conversation_id, sender_type, message_content, intent, sentiment)
                VALUES (%s, %s, %s, %s, %s)
            """, (conversation_id, sender_type, content, intent, sentiment))
            
            cursor.execute("""
                UPDATE conversations 
                SET message_count = message_count + 1
                WHERE conversation_id = %s
            """, (conversation_id,))
            
            conn.commit()
    
    def get_conversation_history(self, conversation_id: str, limit: int = 10) -> List[Dict]:
        """Get recent conversation history"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT sender_type, message_content, message_timestamp, intent, sentiment
                FROM conversation_messages
                WHERE conversation_id = %s
                ORDER BY message_timestamp DESC
                LIMIT %s
            """, (conversation_id, limit))
            
            messages = cursor.fetchall()
            return list(reversed(messages))
    
    def save_context(self, conversation_id: str, context_type: str, context_data: Dict):
        """Save conversation context for future reference"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            cursor.execute("""
                INSERT INTO conversation_context 
                (session_id, context_type, context_data)
                VALUES (%s, %s, %s)
            """, (conversation_id, context_type, json.dumps(context_data)))
            
            conn.commit()

# ============================================================================
# EMAIL HANDLER
# ============================================================================

class EmailHandler:
    """Handles email operations"""
    
    def __init__(self, email_address: str, password: str, imap_server: str, 
                 smtp_server: str, smtp_port: int, db_manager: DatabaseManager, 
                 response_generator_agent=None):
        self.email_address = email_address
        self.password = password
        self.imap_server = imap_server
        self.smtp_server = smtp_server
        self.smtp_port = smtp_port
        self.db_manager = db_manager
        self.ticket_manager = TicketManager(db_manager)
        self.approval_manager = ApprovalManager(db_manager)
        self.response_generator_agent = response_generator_agent
    
    def set_response_generator(self, agent):
        """Set the response generator agent after initialization"""
        self.response_generator_agent = agent
    
    def send_approval_email(self, hr_email: str, ticket_id: str, 
                          job_details: Dict[str, Any], approval_token: str) -> bool:
        """Send approval request email to HR using LLM to generate content"""
        try:
            if self.response_generator_agent:
                prompt = f"""Generate a professional approval request email for HR.

Context:
- A new job posting request has been received
- HR approval is required before it appears on the website
- Ticket ID: {ticket_id}
- Approval Token: {approval_token}

Job Details:
- Job Title: {job_details.get('job_title', 'NOT_FOUND')}
- Location: {job_details.get('location', 'NOT_FOUND')}
- Experience Required: {job_details.get('experience_required', 'NOT_FOUND')}
- Salary Range: {job_details.get('salary_range', 'NOT_FOUND')}
- Employment Type: {job_details.get('employment_type', 'NOT_FOUND')}
- Application Deadline: {job_details.get('deadline', 'NOT_FOUND')}
- Job Description: {job_details.get('job_description', 'NOT_FOUND')}
- Required Skills: {job_details.get('required_skills', 'NOT_FOUND')}

Instructions to include in the email:
- To approve: Reply with "APPROVE {approval_token}"
- To reject: Reply with "REJECT {approval_token} [reason]"
- Once approved, the job will automatically appear on the website
- Note: Once approved, this job posting cannot be modified. To make changes after approval, you'll need to terminate this posting and create a new one.

Make the email professional, clear, and include all job details in a well-formatted way.
Start with "Dear HR Team," and end with "Best regards,\nAI Email Assistant"
"""
                
                response = self.response_generator_agent.generate_reply(
                    messages=[{"content": prompt, "role": "user"}]
                )
                
                email_body = clean_response_text(response)
                
                if not email_body or len(email_body.strip()) < 50:
                    logger.warning("LLM generated insufficient content, using fallback")
                    email_body = self._get_fallback_approval_email(hr_email, ticket_id, job_details, approval_token)
            else:
                logger.warning("No LLM agent available for approval email generation")
                email_body = self._get_fallback_approval_email(hr_email, ticket_id, job_details, approval_token)
            
            msg = EmailMessage()
            msg['Subject'] = f"[APPROVAL REQUIRED] Job Posting - {job_details.get('job_title', 'Unknown Position')}"
            msg['From'] = self.email_address
            msg['To'] = hr_email
            msg.set_content(email_body)
            
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.password)
                server.send_message(msg)
            
            logger.info(f"Approval email sent to {hr_email} for ticket {ticket_id}")
            return True
            
        except Exception as e:
            logger.error(f"Error sending approval email: {e}")
            return False
    
    def _get_fallback_approval_email(self, hr_email: str, ticket_id: str, 
                                    job_details: Dict[str, Any], approval_token: str) -> str:
        """Fallback approval email template if LLM fails"""
        job_summary = f"""
Job Title: {job_details.get('job_title', 'NOT_FOUND')}
Location: {job_details.get('location', 'NOT_FOUND')}
Experience Required: {job_details.get('experience_required', 'NOT_FOUND')}
Salary Range: {job_details.get('salary_range', 'NOT_FOUND')}
Employment Type: {job_details.get('employment_type', 'NOT_FOUND')}
Application Deadline: {job_details.get('deadline', 'NOT_FOUND')}

Job Description:
{job_details.get('job_description', 'NOT_FOUND')}

Required Skills:
{job_details.get('required_skills', 'NOT_FOUND')}
"""
        
        return f"""Dear HR Team,

A new job posting request has been received and requires your approval before it appears on the website.

TICKET ID: {ticket_id}
APPROVAL TOKEN: {approval_token}

JOB DETAILS:
{job_summary}

TO APPROVE AND PUBLISH THIS JOB:
Reply to this email with: APPROVE {approval_token}

TO REJECT THIS POSTING:
Reply to this email with: REJECT {approval_token} [reason]

Note: Once approved, the job will automatically appear on the website and cannot be modified. To make changes after approval, you'll need to terminate this posting and create a new one.

Best regards,
AI Email Assistant"""
    
    def process_approval_response(self, email_body: str, sender: str) -> Tuple[bool, str]:
        """Process approval/rejection responses from HR - FIXED VERSION"""
        logger.info(f"Processing approval response from {sender}")
        logger.info(f"Email body preview: {email_body[:200]}...")
        
        # First check for explicit APPROVE pattern (with or without space)
        approve_match = re.search(r'APPROVE\s*([a-zA-Z0-9]{32})', email_body, re.IGNORECASE)
        if approve_match:
            token = approve_match.group(1)
            logger.info(f"Found APPROVE token: {token}")
            
            success, message, ticket_id = self.approval_manager.process_approval(token)
            
            if success and ticket_id:
                if self.ticket_manager.approve_ticket(ticket_id):
                    return True, f"Job approved and published to website. Ticket ID: {ticket_id}"
                else:
                    return True, "Approval processed but failed to update ticket status"
            else:
                logger.warning(f"Approval processing failed: {message}")
                return True, message
        
        # Check for explicit REJECT pattern
        reject_match = re.search(r'REJECT\s*([a-zA-Z0-9]{32})\s*(.*)', email_body, re.IGNORECASE)
        if reject_match:
            token = reject_match.group(1)
            reason = reject_match.group(2).strip() or "No reason provided"
            logger.info(f"Found REJECT token: {token} with reason: {reason}")
            
            success, message, ticket_id = self.approval_manager.process_rejection(token, reason)
            
            if success and ticket_id:
                with self.db_manager.get_connection() as conn:
                    cursor = conn.cursor()
                    cursor.execute("""
                        UPDATE tickets 
                        SET approval_status = 'rejected',
                            approved = FALSE,
                            rejected_at = NOW(),
                            rejection_reason = %s
                        WHERE ticket_id = %s
                    """, (reason, ticket_id))
                    conn.commit()
                    
                logger.info(f"Updated ticket {ticket_id} as rejected")
            
            return True, message
        
        # Check if the email contains just "APPROVE" or "APPROVED" without token
        if re.search(r'\b(APPROVE|APPROVED)\b', email_body, re.IGNORECASE):
            # Look for the token elsewhere in the email
            token_match = re.search(r'([a-zA-Z0-9]{32})', email_body)
            if token_match:
                token = token_match.group(1)
                logger.info(f"Found APPROVE command and token separately: {token}")
                
                success, message, ticket_id = self.approval_manager.process_approval(token)
                
                if success and ticket_id:
                    if self.ticket_manager.approve_ticket(ticket_id):
                        return True, f"Job approved and published to website. Ticket ID: {ticket_id}"
                    else:
                        return True, "Approval processed but failed to update ticket status"
                else:
                    logger.warning(f"Approval processing failed: {message}")
                    return True, message
        
        # NEW: Check if email contains just the approval token without explicit command
        # This handles cases where user just forwards/replies with the token
        token_only_match = re.search(r'(?:Approval Token:\s*)?([a-zA-Z0-9]{32})', email_body, re.IGNORECASE)
        if token_only_match:
            token = token_only_match.group(1)
            logger.info(f"Found token without explicit command: {token}")
            
            # Check if this is a valid pending approval token
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT pa.*, t.sender as original_sender,
                           td.field_value as job_title
                    FROM pending_approvals pa
                    JOIN tickets t ON pa.ticket_id = t.ticket_id
                    LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                        AND td.field_name = 'job_title' AND td.is_initial = TRUE
                    WHERE pa.approval_token = %s AND pa.status = 'pending'
                """, (token,))
                
                approval_info = cursor.fetchone()
                
                if approval_info:
                    # Valid token found - ask for clarification
                    logger.info(f"Valid token found for ticket {approval_info['ticket_id']}, but no clear command")
                    return True, f"Token recognized for '{approval_info['job_title']}' (Ticket: {approval_info['ticket_id']}). Please reply with either 'APPROVE {token}' or 'REJECT {token} [reason]' to complete the action."
        
        # No valid approval/rejection pattern found
        logger.info("No valid approval/rejection command found")
        return False, "No valid approval/rejection command found. Please use 'APPROVE [token]' or 'REJECT [token] [reason]'"
    
    def fetch_emails(self, max_emails: int = 10, folder: str = "INBOX") -> Tuple[List[Tuple], Any]:
        """Connect to email server and fetch unread emails"""
        try:
            logger.info(f"Connecting to {self.imap_server}...")
            mail = imaplib.IMAP4_SSL(self.imap_server)
            mail.login(self.email_address, self.password)
            mail.select(folder)
            
            status, email_ids = mail.search(None, '(UNSEEN)')
            email_id_list = email_ids[0].split()
            
            if not email_id_list:
                logger.info("No unread emails found")
                return [], mail
            
            emails = []
            for e_id in email_id_list[-max_emails:]:
                status, msg_data = mail.fetch(e_id, '(RFC822)')
                raw_email = msg_data[0][1]
                msg = email.message_from_bytes(raw_email)
                emails.append((e_id, msg))
            
            logger.info(f"Found {len(emails)} emails to process")
            return emails, mail
            
        except Exception as e:
            logger.error(f"Error fetching emails: {e}")
            return [], None
    
    def extract_email_body(self, msg: email.message.Message) -> str:
        """Extract the body text from an email message"""
        body = ""
        
        if msg.is_multipart():
            for part in msg.walk():
                content_type = part.get_content_type()
                content_disposition = str(part.get("Content-Disposition"))
                
                if "attachment" in content_disposition:
                    continue
                
                if content_type == "text/plain" and "attachment" not in content_disposition:
                    body_bytes = part.get_payload(decode=True)
                    if body_bytes:
                        try:
                            body += body_bytes.decode()
                        except UnicodeDecodeError:
                            body += body_bytes.decode('latin-1')
                            
                elif content_type == "text/html" and "attachment" not in content_disposition and not body:
                    html_bytes = part.get_payload(decode=True)
                    if html_bytes:
                        try:
                            html_text = html_bytes.decode()
                        except UnicodeDecodeError:
                            html_text = html_bytes.decode('latin-1')
                        body += re.sub('<[^<]+?>', '', html_text)
        else:
            payload = msg.get_payload(decode=True)
            if payload:
                try:
                    body = payload.decode()
                except UnicodeDecodeError:
                    body = payload.decode('latin-1')
                
                if msg.get_content_type() == "text/html":
                    body = re.sub('<[^<]+?>', '', body)
        
        return body.strip()
    
    def send_email(self, to_address: str, subject: str, body: str, 
                   reply_to_msg_id: Optional[str] = None) -> bool:
        """Send an email"""
        try:
            logger.info(f"Preparing to send email to: {to_address}")
            logger.info(f"Subject: {subject}")
            logger.info(f"Body preview: {body[:100]}...")
            
            msg = EmailMessage()
            msg['Subject'] = subject
            msg['From'] = self.email_address
            msg['To'] = to_address
            msg.set_content(body)
            
            if reply_to_msg_id:
                msg['In-Reply-To'] = reply_to_msg_id
                logger.info(f"Setting In-Reply-To: {reply_to_msg_id}")
            
            logger.info(f"Connecting to SMTP server {self.smtp_server}:{self.smtp_port}")
            with smtplib.SMTP(self.smtp_server, self.smtp_port) as server:
                server.starttls()
                server.login(self.email_address, self.password)
                logger.info("SMTP login successful, sending message...")
                server.send_message(msg)
                logger.info(f"Email sent successfully to {to_address}")
            
            return True
        except Exception as e:
            logger.error(f"Error sending email: {e}")
            import traceback
            traceback.print_exc()
            return False
    
    def mark_as_read(self, mail: imaplib.IMAP4_SSL, email_id: bytes) -> None:
        """Mark an email as read"""
        try:
            mail.store(email_id, '+FLAGS', '\\Seen')
            logger.info(f"Marked email {email_id.decode()} as read")
        except Exception as e:
            logger.error(f"Error marking email as read: {e}")
    
    def get_email_sender(self, msg: email.message.Message) -> str:
        """Extract sender email address"""
        sender = msg['From']
        if '<' in sender and '>' in sender:
            return sender[sender.find('<')+1:sender.find('>')]
        return sender
    
    def get_email_subject(self, msg: email.message.Message) -> str:
        """Extract subject from email message"""
        subject = msg['Subject'] or ""
        if 'APPROVAL REQUIRED' in subject or 'APPROVE' in msg.get_payload(decode=True).decode()[:200] if msg.get_payload(decode=True) else '':
            return subject
        elif not subject.lower().startswith('re:'):
            return f"Re: {subject}"
        return subject

# ============================================================================
# CUSTOM AUTOGEN AGENTS - FIXED VERSION
# ============================================================================

class EmailClassifierAgent(AssistantAgent):
    """Agent responsible for classifying emails - ENHANCED VERSION"""
    
    def __init__(self, name: str, llm_config: Dict):
        system_message = """You are an email classifier for a hiring/recruitment system. Classify emails and return JSON only.

CRITICAL RULES:
1. ANY email that mentions updating, changing, or modifying job-related information MUST be classified as is_hiring_email=true
2. If an email contains "update" AND a ticket ID, it's ALWAYS a hiring email
3. Ignore "Re:" or "Fwd:" prefixes when analyzing

Return this JSON structure:
{
    "is_hiring_email": true/false,
    "is_termination_request": true/false,
    "is_approval_response": true/false,
    "is_conversational": true/false,
    "ticket_id": "extracted_id" or null,
    "confidence": 0.0-1.0,
    "reason": "brief explanation"
}

CLASSIFICATION RULES:

**is_hiring_email = TRUE when:**
- Email contains hiring keywords: job, hiring, position, salary, experience, location, deadline, skills, requirements
- Email contains update words (update, modify, change, revise, edit) + ANY job field (salary, experience, location, etc.)
- Email says "update" with a ticket ID (even without other keywords)
- Email mentions creating or posting a new job
- Examples that MUST be classified as hiring:
  * "update Ticket ID 532bc03c3a experience 8-10"
  * "update the salary"
  * "change deadline to next month"
  * "modify experience requirements"

**is_termination_request = TRUE when:**
- Contains: terminate, close ticket, cancel ticket, position filled, job filled, no longer hiring

**is_approval_response = TRUE when:**
- Contains APPROVE or REJECT followed by a 32-character token

**is_conversational = TRUE when:**
- Questions about the system: how do I, what is, can you help
- Greetings without hiring content
- Status checks or general queries

**ticket_id extraction:**
- Look for exactly 10 characters (lowercase letters a-f and numbers 0-9)
- Common patterns: "Ticket ID: xxx", "ticket xxx", "#xxx"

IMPORTANT: When in doubt about update emails, if it mentions "update" and has a ticket ID, mark it as is_hiring_email=true."""
        
        super().__init__(
            name=name,
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )


class HiringDetailsExtractorAgent(AssistantAgent):
    """Agent responsible for extracting hiring details from emails"""
    
    def __init__(self, name: str, llm_config: Dict):
        system_message = """Extract hiring details from emails. Return ONLY a JSON object.
        
        Fields to extract:
        - job_title: The job position/role name
        - location: Work location/city
        - experience_required: Years of experience
        - salary_range: Salary/compensation
        - job_description: Role description
        - required_skills: Skills needed
        - employment_type: Full-time/Part-time/Contract
        - deadline: Application deadline
        
        Use "NOT_FOUND" for missing fields.
        
        IMPORTANT: For updates, extract ONLY the fields that are mentioned as updated/revised."""
        super().__init__(
            name=name,
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

class ResponseGeneratorAgent(AssistantAgent):
    """Agent responsible for generating email responses"""
    
    def __init__(self, name: str, llm_config: Dict):
        system_message = """Generate professional email responses. Return the complete email body text.
        
        Always start with "Dear [Name]," or "Dear HR Team," and end with "Best regards,\nAI Email Assistant"
        
        IMPORTANT: Return ONLY the email body text, no JSON or other formatting."""
        super().__init__(
            name=name,
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

class ConversationalAgent(AssistantAgent):
    """Agent for handling general conversations and Q&A"""
    
    def __init__(self, name: str, llm_config: Dict):
        system_message = """You are a helpful AI assistant for an EMAIL-BASED hiring/recruitment system. 
        
        IMPORTANT: This is an EMAIL-ONLY system. Users interact ONLY by sending emails to our email address.
        
        When users ask how to post jobs, explain:
        1. Send an email to our system
        2. The email should have "Hiring:" in the subject line
        3. The email body must include ALL required fields
        
        Be friendly, professional, and always provide EMAIL-SPECIFIC instructions."""
        
        super().__init__(
            name=name,
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

class IntentClassifierAgent(AssistantAgent):
    """Agent for classifying user intent in conversational emails"""
    
    def __init__(self, name: str, llm_config: Dict):
        system_message = """Classify the intent of conversational emails. Return JSON only:
        {
            "primary_intent": "conversation|question|help|status_check|list_jobs|feedback|complaint",
            "is_conversational": true/false,
            "needs_data": true/false,
            "data_type": "ticket|jobs|statistics|help_topic",
            "specific_query": "extracted specific question or request",
            "sentiment": "positive|neutral|negative",
            "urgency": "low|medium|high"
        }"""
        
        super().__init__(
            name=name,
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )


# ============================================================================
# CONVERSATIONAL EMAIL PROCESSOR
# ============================================================================

class ConversationalEmailProcessor:
    """Processes conversational emails"""
    
    def __init__(self, conversation_manager: ConversationManager, 
                 ticket_manager: TicketManager, db_manager: DatabaseManager):
        self.conversation_manager = conversation_manager
        self.ticket_manager = ticket_manager
        self.db_manager = db_manager
    
    def process_conversational_email(self, email_data: Dict, agents: Dict) -> Dict:
        """Process a conversational email"""
        logger.info(f"Processing conversational email from {email_data['sender']}")
        
        conversation_id = self.conversation_manager.get_or_create_conversation(email_data['sender'])
        
        intent_prompt = f"""
        Analyze this conversational email:
        Subject: {email_data['subject']}
        Body: {email_data['body']}
        """
        
        intent_response = agents["intent_classifier"].generate_reply(
            messages=[{"content": intent_prompt, "role": "user"}]
        )
        
        intent_data = extract_json_from_text(intent_response)
        if not intent_data:
            intent_data = {
                "primary_intent": "conversation",
                "is_conversational": True,
                "needs_data": False,
                "specific_query": email_data['body'][:200]
            }
        
        self.conversation_manager.add_message(
            conversation_id, "user", email_data['body'],
            intent_data.get('primary_intent'), intent_data.get('sentiment')
        )
        
        history = self.conversation_manager.get_conversation_history(conversation_id)
        
        context = self._prepare_context(email_data, intent_data, history)
        
        response_prompt = self._build_conversation_prompt(
            email_data, intent_data, context, history
        )
        
        response = agents["conversational"].generate_reply(
            messages=[{"content": response_prompt, "role": "user"}]
        )
        
        response_body = clean_response_text(response)
        
        self.conversation_manager.add_message(conversation_id, "assistant", response_body)
        
        return {
            "conversation_id": conversation_id,
            "intent": intent_data.get('primary_intent'),
            "response": response_body,
            "needs_followup": intent_data.get('urgency') == 'high'
        }
    
    def _prepare_context(self, email_data: Dict, intent_data: Dict, 
                        history: List[Dict]) -> Dict:
        """Prepare context data based on intent"""
        context = {
            "user_email": email_data['sender'],
            "has_history": len(history) > 0
        }
        
        if intent_data.get('needs_data'):
            data_type = intent_data.get('data_type')
            
            if data_type == 'ticket':
                ticket_id = self._extract_ticket_from_query(intent_data.get('specific_query', ''))
                if ticket_id:
                    ticket_details = self.ticket_manager.get_ticket_details(ticket_id)
                    if ticket_details:
                        context['ticket_data'] = ticket_details
            
            elif data_type == 'jobs':
                context['jobs'] = self._get_relevant_jobs(email_data['sender'])
            
            elif data_type == 'statistics':
                context['statistics'] = self._get_system_statistics()
        
        return context
    
    def _build_conversation_prompt(self, email_data: Dict, intent_data: Dict,
                                  context: Dict, history: List[Dict]) -> str:
        """Build prompt for conversational response"""
        prompt_parts = [
            f"Generate a helpful email response for this conversation.",
            f"\nIMPORTANT CONTEXT: We are an EMAIL-ONLY hiring system.",
            f"\nUser: {email_data['sender']}",
            f"Subject: {email_data['subject']}",
            f"Current Message: {email_data['body']}",
            f"\nIntent: {intent_data.get('primary_intent')}",
            f"Specific Query: {intent_data.get('specific_query')}"
        ]
        
        if 'post' in email_data['body'].lower() and 'job' in email_data['body'].lower():
            prompt_parts.append("\nThe user is asking how to post jobs. Explain the email-based process.")
        
        if history and len(history) > 1:
            prompt_parts.append("\nRecent Conversation History:")
            for msg in history[-5:]:
                sender = "User" if msg['sender_type'] == 'user' else "Assistant"
                prompt_parts.append(f"{sender}: {msg['message_content'][:200]}...")
        
        prompt_parts.append("\nProvide a helpful, friendly response")
        prompt_parts.append("End with 'Best regards,\\nAI Hiring Assistant'")
        
        return "\n".join(prompt_parts)
    
    def _extract_ticket_from_query(self, query: str) -> Optional[str]:
        """Extract ticket ID from conversational query"""
        patterns = [
            r'ticket\s*(?:id\s*)?([a-f0-9]{10})',
            r'#([a-f0-9]{10})',
            r'about\s+([a-f0-9]{10})',
            r'status\s+of\s+([a-f0-9]{10})'
        ]
        
        for pattern in patterns:
            match = re.search(pattern, query.lower())
            if match:
                return match.group(1)
        return None
    
    def _get_relevant_jobs(self, user_email: str) -> List[Dict]:
        """Get jobs relevant to the user"""
        user_tickets = self.ticket_manager.get_sender_tickets(user_email)
        
        if user_tickets:
            return user_tickets
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT t.ticket_id as id, td.field_value as job_title,
                       t.approved_at, t.source
                FROM tickets t
                JOIN ticket_details td ON t.ticket_id = td.ticket_id
                WHERE t.approval_status = 'approved'
                AND td.field_name = 'job_title'
                AND td.is_initial = TRUE
                ORDER BY t.approved_at DESC
                LIMIT 10
            """)
            return cursor.fetchall()
    
    def _get_system_statistics(self) -> Dict:
        """Get system statistics"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            
            stats = {}
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE status != 'terminated'")
            stats['total_active'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE approval_status = 'approved'")
            stats['approved_jobs'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM pending_approvals WHERE status = 'pending'")
            stats['pending_approvals'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE source = 'email'")
            stats['email_tickets'] = cursor.fetchone()[0]
            
            cursor.execute("SELECT COUNT(*) FROM tickets WHERE source = 'chat'")
            stats['chat_tickets'] = cursor.fetchone()[0]
            
            return stats

# ============================================================================
# EMAIL PROCESSING ORCHESTRATOR - FIXED VERSION
# ============================================================================

class EmailProcessingOrchestrator(UserProxyAgent):
    """Enhanced orchestrator with conversational support and fixed approval handling"""
    
    def __init__(self, name: str, email_handler: EmailHandler):
        super().__init__(
            name=name,
            human_input_mode="NEVER",
            max_consecutive_auto_reply=10,
            code_execution_config=False,
            llm_config=False,
            system_message="You are the orchestrator. Process emails step by step."
        )
        self.email_handler = email_handler
        self.ticket_manager = email_handler.ticket_manager
        self.approval_manager = email_handler.approval_manager
        self.conversation_manager = ConversationManager(email_handler.db_manager)
        self.conversational_processor = ConversationalEmailProcessor(
            self.conversation_manager,
            self.ticket_manager,
            email_handler.db_manager
        )
    
    def process_email_workflow(self, email_data: Dict[str, str], 
                             agents: Dict[str, AssistantAgent]) -> Dict[str, Any]:
        """Enhanced workflow with conversational support and fixed approval handling"""
        results = {
            "sender": email_data["sender"],
            "subject": email_data["subject"],
            "action_taken": None,
            "response_sent": False
        }
        
        # Check if this is an approval response
        is_approval_response, approval_message = self.email_handler.process_approval_response(
            email_data["body"], email_data["sender"]
        )
        
        if is_approval_response:
            logger.info("Processing approval response workflow")
            results["action_taken"] = approval_message
            
            # Extract token from the message
            token_match = re.search(r'([a-zA-Z0-9]{32})', email_data["body"])
            
            if token_match:
                token = token_match.group(1)
                logger.info(f"Found token: {token}")
                
                # Get approval info from database
                with self.email_handler.db_manager.get_connection() as conn:
                    cursor = conn.cursor(dictionary=True)
                    cursor.execute("""
                        SELECT pa.*, t.sender as original_sender,
                               td.field_value as job_title
                        FROM pending_approvals pa
                        JOIN tickets t ON pa.ticket_id = t.ticket_id
                        LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                            AND td.field_name = 'job_title' AND td.is_initial = TRUE
                        WHERE pa.approval_token = %s
                    """, (token,))
                    
                    approval_info = cursor.fetchone()
                
                response_body = ""
                
                if approval_info:
                    ticket_id = approval_info['ticket_id']
                    job_title = approval_info['job_title'] or 'Unknown Position'
                    
                    # Check what type of response this is
                    if "Token recognized" in approval_message:
                        # User sent just the token - ask for clarification
                        response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for your response regarding the job posting for "{job_title}" (Ticket ID: {ticket_id}).

I found the approval token, but I need you to explicitly state your decision.

To APPROVE this job posting and publish it on the website, please reply with:
APPROVE {token}

To REJECT this job posting, please reply with:
REJECT {token} [your reason]

Example responses:
- "APPROVE {token}"
- "REJECT {token} Position already filled"

Please reply with your decision.

Best regards,
AI Email Assistant"""
                    
                    elif "already processed" in approval_message:
                        approval_status = approval_info['status']
                        if approval_status == 'approved':
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

The job posting for "{job_title}" (Ticket ID: {ticket_id}) was already approved and is currently published on the website.

No further action is needed.

Best regards,
AI Email Assistant"""
                        else:
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

This job posting was already processed and rejected previously.

To create a new job posting, please submit a new hiring request.

Best regards,
AI Email Assistant"""
                    
                    elif "approved and published" in approval_message or "Job approved" in approval_message:
                        response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for your approval!

The job posting for "{job_title}" (Ticket ID: {ticket_id}) has been successfully approved and is now published on the website.

The job is now visible to candidates and ready to receive applications.

Note: Now that this job is approved, it cannot be modified. To make changes, you'll need to terminate this posting and create a new one.

Best regards,
AI Email Assistant"""
                    
                    elif "rejected" in approval_message and "Token recognized" not in approval_message:
                        response_body = f"""Dear {email_data['sender'].split('@')[0]},

The job posting for "{job_title}" (Ticket ID: {ticket_id}) has been rejected as requested.

The job will not appear on the website.

Best regards,
AI Email Assistant"""
                    
                    else:
                        # Other cases
                        response_body = f"""Dear {email_data['sender'].split('@')[0]},

{approval_message}

Best regards,
AI Email Assistant"""
                else:
                    # Token not found in database
                    response_body = f"""Dear {email_data['sender'].split('@')[0]},

The approval token provided is not valid or has expired.

Please check the token and try again, or contact the system administrator.

Best regards,
AI Email Assistant"""
            else:
                # No token found at all
                response_body = f"""Dear {email_data['sender'].split('@')[0]},

I couldn't find an approval token in your response.

To approve or reject a job posting, please include the complete 32-character approval token from the original approval request email.

Best regards,
AI Email Assistant"""
            
            # Always send a response for approval-related emails
            if response_body:
                sent = self.email_handler.send_email(
                    email_data["sender"],
                    email_data["subject"],
                    response_body,
                    email_data.get("message_id")
                )
                results["response_sent"] = sent
            
            return results
        
        # Continue with existing workflow for non-approval emails
        
        # Step 1: Classify email with enhanced prompt
        classification_prompt = f"""
        Classify this email:
        Subject: {email_data['subject']}
        Body: {email_data['body']}
        
        IMPORTANT: If the email mentions updating, changing, or modifying any job-related information 
        (like salary, location, deadline, etc.), it should be classified as is_hiring_email=true, 
        even if it's a short message like "update the salary".
        """
        
        classification_response = agents["classifier"].generate_reply(
            messages=[{"content": classification_prompt, "role": "user"}]
        )
        
        classification = extract_json_from_text(classification_response)
        
        if classification is None:
            classification = {
                "is_hiring_email": self._is_hiring_email(email_data['subject'], email_data['body']),
                "is_termination_request": self._is_termination_request(email_data['body']),
                "is_conversational": self._is_conversational_email(email_data['subject'], email_data['body']),
                "ticket_id": self._extract_ticket_id(email_data['body']),
                "confidence": 0.7,
                "reason": "Fallback classification"
            }
        
        # Check if it's conversational
        if classification.get('is_conversational'):
            logger.info("Processing as conversational email")
            
            conv_result = self.conversational_processor.process_conversational_email(
                email_data, agents
            )
            
            sent = self.email_handler.send_email(
                email_data["sender"],
                email_data["subject"],
                conv_result["response"],
                email_data.get("message_id")
            )
            
            return {
                "sender": email_data["sender"],
                "subject": email_data["subject"],
                "action_taken": f"Conversational response ({conv_result['intent']})",
                "response_sent": sent,
                "conversation_id": conv_result["conversation_id"]
            }
        
        # Check for ticket ID
        classifier_ticket_id = classification.get("ticket_id")
        if classifier_ticket_id and len(str(classifier_ticket_id)) != 10:
            classifier_ticket_id = None
            
        if not classifier_ticket_id:
            extracted_ticket_id = self._extract_ticket_id(email_data['body'])
            if extracted_ticket_id:
                classification["ticket_id"] = extracted_ticket_id
        
        logger.info(f"Final classification result: {classification}")
        
        # Process based on classification
        if classification.get("is_termination_request"):
            ticket_id = classification.get("ticket_id")
            if ticket_id and self.ticket_manager.get_ticket_details(ticket_id):
                ticket_details = self.ticket_manager.get_ticket_details(ticket_id)
                original_sender = ticket_details.get("sender", "")
                
                if email_data["sender"].lower() != original_sender.lower():
                    logger.warning(f"Sender {email_data['sender']} trying to terminate ticket created by {original_sender}")
                    results["action_taken"] = "Unauthorized termination attempt"
                    
                    response_body = f"""Dear {email_data['sender'].split('@')[0]},

You cannot terminate ticket {ticket_id} because it was created by {original_sender}.

Only the original job poster can terminate their tickets.

Best regards,
AI Email Assistant"""
                    
                    sent = self.email_handler.send_email(
                        email_data["sender"],
                        email_data["subject"],
                        response_body,
                        email_data.get("message_id")
                    )
                    results["response_sent"] = sent
                    return results
                
                reason = self._extract_termination_reason(email_data["body"])
                success = self.ticket_manager.terminate_ticket(ticket_id, email_data["sender"], reason)
                
                if success:
                    results["action_taken"] = f"Terminated ticket {ticket_id}"
                    
                    was_posted = ticket_details.get("approval_status") == "approved"
                    
                    response_prompt = f"""
                    Generate a ticket termination confirmation email for:
                    Ticket ID: {ticket_id}
                    Sender: {email_data['sender']}
                    Reason: {reason}
                    Was Approved: {was_posted}
                    Scenario: ticket_terminated
                    """
                    
                    response_body = agents["response_generator"].generate_reply(
                        messages=[{"content": response_prompt, "role": "user"}]
                    )
                    
                    response_body = clean_response_text(response_body)
                    
                    if not response_body or len(response_body.strip()) < 10:
                        posted_msg = ""
                        if was_posted:
                            posted_msg = "\n\nThe job posting has been removed from the website display."
                        
                        response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for your email. I have successfully terminated ticket {ticket_id}.

The hiring position has been closed as requested.
Reason: {reason}

The ticket status has been updated to 'terminated' in our system.{posted_msg}

Best regards,
AI Email Assistant"""
                    
                    sent = self.email_handler.send_email(
                        email_data["sender"],
                        email_data["subject"],
                        response_body,
                        email_data.get("message_id")
                    )
                    results["response_sent"] = sent
                else:
                    results["action_taken"] = f"Failed to terminate ticket {ticket_id}"
            else:
                results["action_taken"] = "Termination request but no valid ticket ID found"
        
        elif classification.get("is_hiring_email"):
            ticket_id = classification.get("ticket_id")
            
            update_indicators = ['update', 'modify', 'change', 'revision', 'edit', 'revised', 'modification']
            subject_lower = email_data['subject'].lower()
            body_lower = email_data['body'].lower()
            is_update_request = any(indicator in subject_lower or indicator in body_lower for indicator in update_indicators)
            
            if is_update_request and not ticket_id:
                logger.info("Update request detected but no ticket ID provided")
                results["action_taken"] = "Update request missing ticket ID"
                
                sender_tickets = self.ticket_manager.get_sender_tickets(email_data['sender'])
                
                if sender_tickets:
                    ticket_list = "\n".join([f"• Ticket ID: {t['id']} - {t['job_title']} (Created: {t['created'][:10]})" 
                                           for t in sender_tickets])
                    response_body = f"""Dear {email_data['sender'].split('@')[0]},

I noticed you're trying to update a hiring position, but the ticket ID is missing from your email.

Please include the ticket ID in your email to proceed with the update. Here are your active tickets:

{ticket_list}

Please resend your update email with the format:
Ticket ID: [10-character-id]
[Your update details]

Example:
Ticket ID: abc123def4
Please update the salary to 20-25 LPA

Best regards,
AI Email Assistant"""
                else:
                    response_body = f"""Dear {email_data['sender'].split('@')[0]},

I noticed you're trying to update a hiring position, but I couldn't find the ticket ID in your email.

Additionally, I don't have any active hiring tickets associated with your email address.

If you have a ticket ID from a previous submission, please include it in your email.

Best regards,
AI Email Assistant"""
                
                sent = self.email_handler.send_email(
                    email_data["sender"],
                    email_data["subject"],
                    response_body,
                    email_data.get("message_id")
                )
                results["response_sent"] = sent
                return results
            
            if ticket_id:
                ticket_id = ticket_id.strip().lower()
                ticket_details = self.ticket_manager.get_ticket_details(ticket_id)
                
                if ticket_details:
                    # Check if it's an approved ticket but allow the update
                    is_approved = ticket_details.get("approval_status") == "approved"
                    
                    logger.info(f"Processing update for existing ticket: {ticket_id}")
                    
                    extraction_prompt = f"""
                    Extract ONLY the updated hiring details from this email update.
                    This is an UPDATE to an existing position, not a new position.
                    
                    Email content:
                    {email_data['body']}
                    
                    Return ONLY a JSON with the fields that are being updated.
                    """
                    
                    extraction_response = agents["extractor"].generate_reply(
                        messages=[{"content": extraction_prompt, "role": "user"}]
                    )
                    
                    extracted_details = extract_json_from_text(extraction_response)
                    
                    if extracted_details is None:
                        extracted_details = self._extract_update_details(email_data['body'], email_data['subject'])
                    
                    update_details = {}
                    for key, value in extracted_details.items():
                        if value and value != "NOT_FOUND" and len(str(value).strip()) > 0:
                            update_details[key] = str(value).strip()
                    
                    existing_ticket = self.ticket_manager.get_ticket_details(ticket_id)
                    merged_details = existing_ticket.get("initial_details", {}).copy()
                    
                    for update in existing_ticket.get("updates", []):
                        merged_details.update(update.get("details", {}))
                    
                    merged_details.update(update_details)
                    
                    ticket_id_returned, is_update, status = self.ticket_manager.create_or_update_ticket_with_id(
                        ticket_id,
                        email_data["sender"],
                        email_data["subject"],
                        update_details,
                        email_data["timestamp"]
                    )
                    
                    results["action_taken"] = f"Ticket {ticket_id} updated"
                    
                    # Check if this was an update to an approved ticket
                    response_prompt = f"""
                    Generate a ticket update confirmation email:
                    Ticket ID: {ticket_id}
                    Sender: {email_data['sender']}
                    Updated fields: {json.dumps(update_details)}
                    All current details: {json.dumps(merged_details)}
                    Was Approved: {is_approved}
                    Scenario: ticket_updated
                    """
                    
                    response_body = agents["response_generator"].generate_reply(
                        messages=[{"content": response_prompt, "role": "user"}]
                    )
                    
                    response_body = clean_response_text(response_body)
                    
                    if not response_body or len(response_body.strip()) < 10:
                        update_lines = []
                        field_names = {
                            "job_title": "Job Title",
                            "location": "Location",
                            "experience_required": "Experience Required",
                            "salary_range": "Salary Range",
                            "job_description": "Job Description",
                            "required_skills": "Required Skills",
                            "employment_type": "Employment Type",
                            "deadline": "Application Deadline"
                        }
                        
                        for key, value in update_details.items():
                            if value and value != "NOT_FOUND":
                                update_lines.append(f"• {field_names.get(key, key)}: {value}")
                        
                        if is_approved:
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for the update on ticket {ticket_id}.

The following information has been updated:
{chr(10).join(update_lines)}

**Important Notice:** This job posting is already live on the website. The changes have been applied immediately and are now visible to all applicants.

The ticket has been successfully updated in our system.

Best regards,
AI Email Assistant"""
                        else:
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for the update on ticket {ticket_id}.

The following information has been updated:
{chr(10).join(update_lines)}

The ticket has been successfully updated in our system.

Best regards,
AI Email Assistant"""
                    
                    sent = self.email_handler.send_email(
                        email_data["sender"],
                        email_data["subject"],
                        response_body,
                        email_data.get("message_id")
                    )
                    results["response_sent"] = sent
                    
                else:
                    logger.warning(f"Ticket ID {ticket_id} provided but not found in system")
                    results["action_taken"] = f"Ticket ID {ticket_id} not found"
                    
                    sender_tickets = self.ticket_manager.get_sender_tickets(email_data['sender'])
                    
                    if sender_tickets:
                        ticket_list = "\n".join([f"• Ticket ID: {t['id']} - {t['job_title']} (Created: {t['created'][:10]})" 
                                               for t in sender_tickets])
                        response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for your email. However, I couldn't find ticket ID {ticket_id} in our system.

Here are your active tickets:
{ticket_list}

Please verify the ticket ID and try again.

Best regards,
AI Email Assistant"""
                    else:
                        response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for your email. However, I couldn't find ticket ID {ticket_id} in our system.

Additionally, I don't have any active hiring tickets associated with your email address.

Please verify the ticket ID or submit a new hiring request.

Best regards,
AI Email Assistant"""
                    
                    sent = self.email_handler.send_email(
                        email_data["sender"],
                        email_data["subject"],
                        response_body,
                        email_data.get("message_id")
                    )
                    results["response_sent"] = sent
                    return results
            
            else:
                # This is a new hiring email
                extraction_prompt = f"""
                Extract hiring details from this email:
                Subject: {email_data['subject']}
                Body: {email_data['body']}
                """
                
                extraction_response = agents["extractor"].generate_reply(
                    messages=[{"content": extraction_prompt, "role": "user"}]
                )
                
                extracted_details = extract_json_from_text(extraction_response)
                
                if extracted_details is None:
                    extracted_details = self._fallback_extraction(email_data['body'])
                
                cleaned_details = {}
                for key in REQUIRED_HIRING_DETAILS:
                    value = extracted_details.get(key, "NOT_FOUND")
                    if value and value != "NOT_FOUND" and len(str(value).strip()) > 0:
                        cleaned_details[key] = str(value).strip()
                    else:
                        cleaned_details[key] = "NOT_FOUND"
                
                extracted_details = cleaned_details
                
                missing_details = [
                    key for key in REQUIRED_HIRING_DETAILS 
                    if extracted_details.get(key) == "NOT_FOUND"
                ]
                
                if missing_details:
                    results["action_taken"] = "Missing required details"
                    response_prompt = f"""
                    Generate an email asking for missing hiring details:
                    Sender: {email_data['sender']}
                    Missing fields: {', '.join(missing_details)}
                    Scenario: missing_details
                    """
                else:
                    ticket_id, is_update, status = self.ticket_manager.create_or_update_ticket(
                        email_data["sender"],
                        email_data["subject"],
                        extracted_details,
                        email_data["timestamp"]
                    )
                    
                    if status == "terminated":
                        results["action_taken"] = f"Ticket {ticket_id} is already terminated"
                    else:
                        action = "updated" if is_update else "created"
                        results["action_taken"] = f"Ticket {ticket_id} {action}"
                        
                        if action == "created":
                            job_details = self.ticket_manager.get_complete_ticket_details(ticket_id)
                            
                            approval_token = self.approval_manager.create_approval_request(
                                ticket_id, 
                                job_details, 
                                email_data["sender"]
                            )
                            
                            with self.email_handler.db_manager.get_connection() as conn:
                                cursor = conn.cursor()
                                cursor.execute("""
                                    UPDATE tickets 
                                    SET approval_token = %s
                                    WHERE ticket_id = %s
                                """, (approval_token, ticket_id))
                                conn.commit()
                            
                            approval_sent = self.email_handler.send_approval_email(
                                email_data["sender"],
                                ticket_id,
                                job_details,
                                approval_token
                            )
                            
                            if approval_sent:
                                results["action_taken"] += " - Approval request sent"
                                response_prompt = f"""
                                Generate a ticket created confirmation email that mentions approval is needed:
                                Ticket ID: {ticket_id}
                                Sender: {email_data['sender']}
                                Details: {json.dumps(extracted_details)}
                                Scenario: ticket_created with approval_sent
                                """
                        else:
                            response_prompt = f"""
                            Generate a ticket {action} confirmation email:
                            Ticket ID: {ticket_id}
                            Sender: {email_data['sender']}
                            Details: {json.dumps(extracted_details)}
                            Scenario: ticket_{action}
                            """
                
                if 'response_prompt' in locals():
                    response_body = agents["response_generator"].generate_reply(
                        messages=[{"content": response_prompt, "role": "user"}]
                    )
                    
                    response_body = clean_response_text(response_body)
                    
                    if not response_body or len(response_body.strip()) < 10:
                        if "Missing required details" in results["action_taken"]:
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for your hiring request. However, I noticed some important details are missing:

{chr(10).join(['• ' + field.replace('_', ' ').title() for field in missing_details])}

Please provide these details so I can properly process your hiring request.

Best regards,
AI Email Assistant"""
                        elif "created" in results["action_taken"] and "Approval request sent" in results["action_taken"]:
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for submitting the hiring request. I have created a new ticket for this position.

Ticket ID: {ticket_id}
Status: Pending Approval

Details recorded:
{json.dumps(extracted_details, indent=2)}

IMPORTANT: An approval request has been sent to you. Please check your email and follow the instructions to approve this job posting before it appears on the website.

Note: Once approved, this job posting cannot be modified. To make changes after approval, you'll need to terminate and create a new posting.

Best regards,
AI Email Assistant"""
                        elif "created" in results["action_taken"]:
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for submitting the hiring request. I have created a new ticket for this position.

Ticket ID: {ticket_id}
Status: New

Details recorded:
{json.dumps(extracted_details, indent=2)}

This information has been saved in our system.

Best regards,
AI Email Assistant"""
                        elif "updated" in results["action_taken"]:
                            response_body = f"""Dear {email_data['sender'].split('@')[0]},

Thank you for the update. The ticket has been successfully updated.

Ticket ID: {ticket_id}
Status: Updated

Your changes have been recorded in our system.

Best regards,
AI Email Assistant"""
                    
                    sent = self.email_handler.send_email(
                        email_data["sender"],
                        email_data["subject"],
                        response_body,
                        email_data.get("message_id")
                    )
                    results["response_sent"] = sent
        
        else:
            results["action_taken"] = "Not a hiring-related email"
        
        return results
    
    def _is_conversational_email(self, subject: str, body: str) -> bool:
        """Check if email is conversational"""
        conversational_keywords = [
            'how do i', 'what is', 'can you', 'could you', 'please help',
            'tell me', 'explain', 'show me', 'list all', 'thank you',
            'thanks', 'hi ', 'hello', 'hey', 'good morning', 'good afternoon',
            'question about', 'help with', 'need help', 'assistance',
            'wondering', 'curious', 'status of', 'check on', 'follow up'
        ]
        
        combined_text = f"{subject} {body}".lower()
        
        for keyword in conversational_keywords:
            if keyword in combined_text:
                return True
        
        if '?' in combined_text:
            return True
        
        return False
    
    def _extract_update_details(self, body: str, subject: str) -> Dict[str, str]:
        """Extract only updated fields from an update email"""
        updates = {}
        
        title_match = re.search(r'(?:Update on|Updated?)\s+(.+?)\s+Position', subject, re.IGNORECASE)
        if title_match:
            updates["job_title"] = title_match.group(1).strip()
        
        update_patterns = {
            "salary_range": [
                r"Salary Range:\s*([^\n]+?)(?:\s*\(revised\))?(?:\n|$)",
                r"Salary:\s*([^\n]+?)(?:\s*\(revised\))?(?:\n|$)",
                r"update.*salary.*to\s*([^\n]+?)(?:\n|$)",
                r"salary.*to\s*([^\n]+?)(?:\n|$)"
            ],
            "experience_required": [
                r"Experience Required:\s*([^\n]+?)(?:\s*\(updated\))?(?:\n|$)",
                r"Experience:\s*([^\n]+?)(?:\s*\(updated\))?(?:\n|$)"
            ],
            "required_skills": [
                r"Additional Skills:\s*([^\n]+?)(?:\n|$)",
                r"Skills:\s*([^\n]+?)(?:\n|$)"
            ],
            "deadline": [
                r"Application Deadline:\s*(?:Extended to\s*)?([^\n]+?)(?:\n|$)",
                r"Deadline:\s*(?:Extended to\s*)?([^\n]+?)(?:\n|$)"
            ],
            "location": [
                r"Location:\s*([^\n]+?)(?:\n|$)",
                r"Office:\s*([^\n]+?)(?:\n|$)"
            ]
        }
        
        for field, patterns in update_patterns.items():
            for pattern in patterns:
                match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip()
                    value = value.rstrip(',.')
                    updates[field] = value
                    break
        
        return updates
    
    def _extract_termination_reason(self, email_body: str) -> str:
        """Extract termination reason from email"""
        reason_patterns = [
            r'reason[:\s]+([^\n]+)',
            r'because[:\s]+([^\n]+)',
            r'position (?:has been )?filled',
            r'no longer (?:need|require|hiring)'
        ]
        
        for pattern in reason_patterns:
            match = re.search(pattern, email_body, re.IGNORECASE)
            if match:
                return match.group(0) if match.lastindex is None else match.group(1)
        
        return "No specific reason provided"
    
    def _is_hiring_email(self, subject: str, body: str) -> bool:
        """Check if email is hiring related - ENHANCED VERSION"""
        hiring_keywords = [
            'job', 'hiring', 'recruitment', 'position', 'vacancy', 'opening', 
            'career', 'employment', 'interview', 'candidate', 'application',
            'salary range', 'salary', 'experience', 'deadline', 'update', 
            'revised', 'requirement', 'skills', 'location', 'modify', 'change',
            'edit', 'correction', 'adjustment', 'revise', 'new'
        ]
        
        # Specific update patterns that indicate hiring-related updates
        update_patterns = [
            r'update.*(?:salary|location|deadline|experience|skills|job|position)',
            r'(?:salary|location|deadline|experience|skills|job|position).*update',
            r'change.*(?:salary|location|deadline|experience|skills|job|position)',
            r'modify.*(?:salary|location|deadline|experience|skills|job|position)',
            r'revise.*(?:salary|location|deadline|experience|skills|job|position)',
            r'edit.*(?:salary|location|deadline|experience|skills|job|position)',
            r'new.*(?:salary|location|deadline|experience|skills)',
            r'update\s+the\s+(?:salary|location|deadline|experience|skills)',
            r'please\s+(?:update|change|modify).*(?:salary|location|deadline)',
        ]
        
        combined_text = f"{subject} {body}".lower()
        
        # First check for specific update patterns
        for pattern in update_patterns:
            if re.search(pattern, combined_text, re.IGNORECASE):
                return True
        
        # Check for general hiring keywords
        matches = sum(1 for keyword in hiring_keywords if keyword in combined_text)
        
        # Lower threshold if "update" or similar words are present
        if any(word in combined_text for word in ['update', 'change', 'modify', 'revise', 'edit']):
            return matches >= 1  # Only need 1 other keyword if update-related word is present
        
        return matches >= 2
    
    def _is_termination_request(self, body: str) -> bool:
        """Check if email is a termination request"""
        termination_keywords = [
            'terminate', 'termination', 'close ticket', 'cancel ticket', 
            'close this ticket', 'cancel this position', 'position filled',
            'job filled', 'hiring closed', 'position closed', 'no longer hiring',
            'withdraw', 'withdrawal', 'cancel job', 'terminate ticket'
        ]
        
        body_lower = body.lower()
        return any(keyword in body_lower for keyword in termination_keywords)
    
    def _extract_ticket_id(self, body: str) -> Optional[str]:
        """Extract ticket ID from email body"""
        patterns = [
            r'ticket\s*id\s*[:\s]*([a-fA-F0-9]{10})',
            r'ticket\s*#\s*([a-fA-F0-9]{10})',
            r'ticket\s*number\s*[:\s]*([a-fA-F0-9]{10})',
            r'#([a-fA-F0-9]{10})\b',
        ]
        
        for pattern in patterns:
            match = re.search(pattern, body, re.IGNORECASE)
            if match:
                ticket_id = match.group(1).lower()
                return ticket_id
        
        return None
    
    def _fallback_extraction(self, body: str) -> Dict[str, str]:
        """Fallback extraction using regex patterns"""
        extracted = {}
        
        patterns = {
            "job_title": [
                r"(?:position|job title|role)[\s:]+([^\n:]+?)(?:\n|:|$)",
                r"(?:hiring for|seeking)\s+(?:a\s+)?([^\n]+?)(?:\s+position|\s+role|\n|:|$)",
                r"for the\s+([^\n]+?)\s+Position"
            ],
            "location": [
                r"(?:location|office|city)[\s:]+([^\n:]+)",
                r"(?:based in|office in)\s+([^\n:]+)"
            ],
            "experience_required": [
                r"Experience Required[\s:]+([^\n:]+)",
                r"Experience[\s:]+(\d+[-\-]\d+\s+years?)",
                r"(\d+[-\-]\d+\s+years?)(?:\s+\(updated\))?",
                r"(\d+\+?\s+years?)"
            ],
            "salary_range": [
                r"Salary Range[\s:]+([^\n:]+?)(?:\s+\(revised\))?",
                r"(?:salary|compensation|ctc)[\s:]+([^\n:]+)",
                r"(?:INR|Rs\.?)\s*([\d,\s\-]+(?:Lakhs?|LPA|L)[^\n]*)"
            ],
            "deadline": [
                r"(?:deadline|last date|apply by|closing date|application deadline)[\s:]+([^\n:]+)",
                r"Extended to\s+([^\n:]+)"
            ],
            "required_skills": [
                r"Additional Skills[\s:]+([^\n:]+)",
                r"(?:required skills|skills|requirements|qualifications|technical requirements)[\s:]+([^\n:]+)",
                r"(?:must have|should have)[\s:]+([^\n:]+)"
            ],
            "job_description": [
                r"(?:job description|description|about the role|role description)[\s:]+([^\n]+(?:\n(?!(?:location|experience|salary|skills|deadline|employment)).*)*))",
                r"(?:responsibilities|duties)[\s:]+([^\n]+(?:\n(?!(?:location|experience|salary|skills|deadline|employment)).*)*)"
            ],
            "employment_type": [
                r"(?:employment type|job type|type)[\s:]+([^\n:]+)",
                r"(full[- ]?time|part[- ]?time|contract|freelance|remote)",
            ]
        }
        
        for field, field_patterns in patterns.items():
            for pattern in field_patterns:
                match = re.search(pattern, body, re.IGNORECASE | re.MULTILINE)
                if match:
                    value = match.group(1).strip()
                    value = value.rstrip(',.')
                    if field == "salary_range":
                        value = re.sub(r'^Range:\s*', '', value, flags=re.IGNORECASE)
                    extracted[field] = value
                    break
            if field not in extracted:
                extracted[field] = "NOT_FOUND"
        
        for field in REQUIRED_HIRING_DETAILS:
            if field not in extracted:
                extracted[field] = "NOT_FOUND"
        
        return extracted

# ============================================================================
# EMAIL HIRING BOT SYSTEM
# ============================================================================

class EmailHiringBotSystem:
    """Enhanced system with conversational AI support"""
    
    def __init__(self, email_handler: EmailHandler, llm_config: Dict):
        self.email_handler = email_handler
        self.llm_config = llm_config
        
        self.agents = {
            "classifier": EmailClassifierAgent("EmailClassifier", llm_config),
            "extractor": HiringDetailsExtractorAgent("DetailsExtractor", llm_config),
            "response_generator": ResponseGeneratorAgent("ResponseGenerator", llm_config),
            "conversational": ConversationalAgent("ConversationalAI", llm_config),
            "intent_classifier": IntentClassifierAgent("IntentClassifier", llm_config)
        }
        
        self.email_handler.set_response_generator(self.agents["response_generator"])
        
        self.orchestrator = EmailProcessingOrchestrator("EmailOrchestrator", email_handler)
    
    def process_emails(self) -> str:
        """Process all unread emails"""
        print("\n" + "="*60)
        print("STARTING EMAIL PROCESSING")
        print("="*60)
        
        logger.info("Starting Email Hiring Bot")
        
        print("Fetching unread emails...")
        emails, mail = self.email_handler.fetch_emails(max_emails=MAX_EMAILS_TO_PROCESS)
        
        if not mail:
            print("❌ Could not connect to email server.")
            return "Could not connect to email server."
        
        if not emails:
            print("📭 No unread emails found.")
            print("\nTo test the bot:")
            print("1. Send an email to:", EMAIL_ADDRESS)
            print("2. Try these examples:")
            print("   - Hiring: 'Hiring: Software Developer Position'")
            print("   - Update: 'Update the salary' (will ask for ticket ID)")
            print("   - Update with ID: 'Ticket ID: abc123def4\\nUpdate salary to 20L'")
            print("   - Conversation: 'How do I post a job?'")
            print("   - Status check: 'What's the status of my tickets?'")
            print("3. Keep the email UNREAD in Gmail")
            print("4. Run this script again")
            return "No unread emails found."
        
        print(f"📧 Found {len(emails)} unread emails to process")
        processed_emails = []
        
        for i, (email_id, msg) in enumerate(emails, 1):
            try:
                email_data = {
                    "sender": self.email_handler.get_email_sender(msg),
                    "subject": self.email_handler.get_email_subject(msg),
                    "body": self.email_handler.extract_email_body(msg),
                    "message_id": msg.get('Message-ID', ''),
                    "timestamp": datetime.now().isoformat()
                }
                
                print(f"\n[{i}/{len(emails)}] Processing email:")
                print(f"   From: {email_data['sender']}")
                print(f"   Subject: {email_data['subject'][:50]}...")
                logger.info(f"Processing email from {email_data['sender']}")
                
                result = self.orchestrator.process_email_workflow(email_data, self.agents)
                
                self.email_handler.mark_as_read(mail, email_id)
                
                status = f"Email from {result['sender']}: {result['action_taken']}"
                if result['response_sent']:
                    status += " (Response sent ✓)"
                    print(f"   ✓ Action: {result['action_taken']}")
                    print(f"   ✓ Response sent")
                else:
                    print(f"   ✓ Action: {result['action_taken']}")
                    print(f"   ⚠ No response sent")
                    
                processed_emails.append(status)
                
            except Exception as e:
                logger.error(f"Error processing email: {e}")
                print(f"   ❌ Error: {str(e)}")
                processed_emails.append(f"Error processing email: {str(e)}")
        
        mail.logout()
        print("\n" + "="*60)
        print("EMAIL PROCESSING COMPLETE")
        print("="*60)
        logger.info("Email processing complete")
        
        return "\n".join(processed_emails) if processed_emails else "No emails processed"

# ============================================================================
# STATUS DISPLAY FUNCTIONS
# ============================================================================

def show_system_status(db_manager: DatabaseManager):
    """Display complete system status from MySQL"""
    print("\n" + "="*60)
    print("SYSTEM STATUS (UNIFIED DATABASE)")
    print("="*60)
    
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("SELECT COUNT(*) as total FROM tickets")
            result = cursor.fetchone()
            total_tickets = result['total'] if result else 0
            
            cursor.execute("""
                SELECT 
                    SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) as approved,
                    SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'terminated' THEN 1 ELSE 0 END) as terminated_count,
                    SUM(CASE WHEN source = 'email' THEN 1 ELSE 0 END) as email_tickets,
                    SUM(CASE WHEN source = 'chat' THEN 1 ELSE 0 END) as chat_tickets
                FROM tickets
            """)
            counts = cursor.fetchone()
            
            print(f"\nTotal Tickets: {total_tickets}")
            print(f"  - From Email: {counts['email_tickets'] or 0}")
            print(f"  - From Chat: {counts['chat_tickets'] or 0}")
            print(f"  - Approved (Website Visible): {counts['approved'] or 0}")
            print(f"  - Pending Approval: {counts['pending'] or 0}")
            print(f"  - Terminated: {counts['terminated_count'] or 0}")
            
            cursor.execute("""
                SELECT COUNT(*) as pending_approvals 
                FROM pending_approvals 
                WHERE status = 'pending'
            """)
            result = cursor.fetchone()
            pending_approvals = result['pending_approvals'] if result else 0
            print(f"\nPending Approval Requests: {pending_approvals}")
            
            print("\nJobs currently visible on website (approval_status='approved'):")
            cursor.execute("""
                SELECT t.ticket_id, t.source, td.field_value as job_title
                FROM tickets t
                LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                    AND td.field_name = 'job_title' AND td.is_initial = TRUE
                WHERE t.approval_status = 'approved'
            """)
            
            approved_jobs = cursor.fetchall()
            if approved_jobs:
                for job in approved_jobs:
                    print(f"  - {job['job_title'] or 'Unknown'} (ID: {job['ticket_id']}, Source: {job['source']})")
            else:
                print("  - No approved jobs currently")
            
            cursor.execute("""
                SELECT COUNT(DISTINCT user_email) as unique_users,
                       COUNT(*) as total_conversations,
                       SUM(message_count) as total_messages
                FROM conversations
                WHERE status = 'active'
            """)
            conv_stats = cursor.fetchone()
            
            if conv_stats and conv_stats['total_conversations'] > 0:
                print(f"\nConversation Statistics:")
                print(f"  - Unique Users: {conv_stats['unique_users']}")
                print(f"  - Total Conversations: {conv_stats['total_conversations']}")
                print(f"  - Total Messages: {conv_stats['total_messages'] or 0}")
                
    except Exception as e:
        print(f"Error reading status: {e}")

def test_mysql_connection(config):
    """Test MySQL connection"""
    try:
        conn = mysql.connector.connect(**config)
        if conn.is_connected():
            logger.info("MySQL connection successful!")
            conn.close()
            return True
    except Error as e:
        logger.error(f"MySQL connection failed: {e}")
        return False

def test_openai_connection():
    """Test OpenAI API connection"""
    try:
        import openai
        from openai import OpenAI
        
        client = OpenAI(api_key=OPENAI_API_KEY)
        
        response = client.chat.completions.create(
            model=OPENAI_MODEL,
            messages=[
                {"role": "user", "content": "Say 'OpenAI connection successful!'"}
            ],
            max_tokens=50,
            temperature=0.1
        )
        
        if response.choices[0].message.content:
            logger.info("OpenAI API connection successful!")
            return True
        else:
            logger.error("OpenAI API returned empty response")
            return False
            
    except Exception as e:
        logger.error(f"Error testing OpenAI connection: {e}")
        return False

# ============================================================================
# MAIN EXECUTION
# ============================================================================

def main():
    """Main function to run the email bot with unified database"""
    print("=" * 60)
    print("EMAIL HIRING BOT - UNIFIED DATABASE")
    print("=" * 60)
    
    if EMAIL_ADDRESS == "your-email@gmail.com":
        print("\nERROR: Please update EMAIL_ADDRESS in the .env file!")
        return
    
    if not EMAIL_PASSWORD:
        print("\nERROR: Please update EMAIL_PASSWORD in the .env file!")
        return
    
    if not OPENAI_API_KEY or OPENAI_API_KEY == "your-openai-api-key-here":
        print("\nERROR: Please update OPENAI_API_KEY in the .env file!")
        return
    
    print(f"\nConfiguration:")
    print(f"Email: {EMAIL_ADDRESS}")
    print(f"Model: {OPENAI_MODEL}")
    print(f"Database: {MYSQL_CONFIG['database']}@{MYSQL_CONFIG['host']}")
    print(f"Max Emails: {MAX_EMAILS_TO_PROCESS}")
    print(f"Unified Database: ENABLED (shared with chat bot)")
    
    print("\n🔌 Testing MySQL connection...")
    if not test_mysql_connection(MYSQL_CONFIG):
        print("❌ Failed to connect to MySQL. Please check your credentials.")
        return
    print("✓ MySQL connection successful!")
    
    print("🗄️ Setting up unified database...")
    db_manager = DatabaseManager(MYSQL_CONFIG)
    print("✓ Database ready")
    
    print("\n🤖 Testing OpenAI API connection...")
    if not test_openai_connection():
        print("❌ Failed to connect to OpenAI API. Please check your API key.")
        return
    print("✓ OpenAI API connection successful!")
    
    email_handler = EmailHandler(
        email_address=EMAIL_ADDRESS,
        password=EMAIL_PASSWORD,
        imap_server=IMAP_SERVER,
        smtp_server=SMTP_SERVER,
        smtp_port=SMTP_PORT,
        db_manager=db_manager
    )
    
    print("\n📧 Testing email connection...")
    try:
        test_mail = imaplib.IMAP4_SSL(IMAP_SERVER)
        test_mail.login(EMAIL_ADDRESS, EMAIL_PASSWORD)
        
        test_mail.select('INBOX')
        status, email_ids = test_mail.search(None, '(UNSEEN)')
        unread_count = len(email_ids[0].split()) if email_ids[0] else 0
        
        test_mail.logout()
        print(f"✓ Email connection successful!")
        print(f"📬 Unread emails in inbox: {unread_count}")
    except Exception as e:
        print(f"❌ Email connection failed: {e}")
        return
    
    show_system_status(db_manager)
    
    try:
        print("\n🚀 Starting email processing...")
        print("✨ Features:")
        print("   - Unified database with chat bot")
        print("   - Conversational AI support")
        print("   - Fixed approval workflow (no accidental rejections)")
        print("   - Enhanced update email classification")
        print("   - Ticket updates and termination")
        print("\n📌 Approval Instructions:")
        print("   - To approve: Reply with 'APPROVE [token]'")
        print("   - To reject: Reply with 'REJECT [token] [reason]'")
        print("   - If you send just the token, bot will ask for clarification")
        print("\n🔧 Update Instructions:")
        print("   - For updates after approval: Bot will guide you to terminate and recreate")
        print("   - Include ticket ID for updates: 'Ticket ID: xxx\\nUpdate salary to 20L'")
        print("   - Short updates like 'update the salary' are now recognized")

        system = EmailHiringBotSystem(email_handler, llm_config)
        result = system.process_emails()
        
        print("\n" + "=" * 60)
        print("FINAL RESULTS")
        print("=" * 60)
        print(result)
        
        show_system_status(db_manager)
        
    except KeyboardInterrupt:
        print("\n\n⚠️ Process interrupted by user.")
    except Exception as e:
        print(f"\n❌ ERROR: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
