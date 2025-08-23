#!/usr/bin/env python3
"""
AI Chat Bot with Unified Database and Language Detection
Modified to share database with Email Bot
Updated to use OpenAI API with language detection feature
"""

import re
import json
from datetime import datetime, timedelta
import hashlib
from typing import Dict, List, Tuple, Optional, Any
import autogen
from autogen import AssistantAgent
import logging
import mysql.connector
from mysql.connector import Error
from contextlib import contextmanager
import secrets
import uuid
import os
from dotenv import load_dotenv

# Load environment variables
load_dotenv()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# ============================================================================
# CONFIGURATION
# ============================================================================

class Config:
    # OpenAI API Configuration (SAME AS EMAIL BOT)
    OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
    OPENAI_MODEL = os.getenv("OPENAI_MODEL", "gpt-3.5-turbo")
    OPENAI_API_BASE = "https://api.openai.com/v1"
    
    # MySQL Configuration (SAME AS EMAIL BOT)
    MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
    MYSQL_USER = os.getenv("MYSQL_USER", "root")
    MYSQL_PASSWORD = os.getenv("MYSQL_PASSWORD", "Khan@123")
    MYSQL_DATABASE = os.getenv("MYSQL_DATABASE", "hiring_bot")  # Same database as email bot
    
    # Debug Mode
    DEBUG_MODE = True  # Allows instant ticket approval in chat
    
    # Required hiring details
    REQUIRED_HIRING_DETAILS = [
        "job_title", "location", "experience_required", "salary_range",
        "job_description", "required_skills", "employment_type", "deadline"
    ]

# Validate configuration
if not Config.OPENAI_API_KEY:
    raise ValueError("OPENAI_API_KEY not found in environment variables!")

# AutoGen LLM Configuration for OpenAI
llm_config = {
    "config_list": [{
        "model": Config.OPENAI_MODEL,
        "api_key": Config.OPENAI_API_KEY,
        "base_url": Config.OPENAI_API_BASE,
        "api_type": "openai",
    }],
    "temperature": 0.1,
    "seed": 42,
    "cache_seed": None,
    "timeout": 120,
    "max_tokens": 1000,
}

# ============================================================================
# UNIFIED DATABASE MANAGER (SHARED WITH EMAIL BOT)
# ============================================================================

class DatabaseManager:
    """Manages MySQL database connections - shared structure with email bot"""
    
    def __init__(self):
        self.config = {
            'host': Config.MYSQL_HOST,
            'user': Config.MYSQL_USER,
            'password': Config.MYSQL_PASSWORD,
            'database': Config.MYSQL_DATABASE
        }
        try:
            self.setup_database()
        except Exception as e:
            logger.error(f"Failed to setup database: {e}")
            logger.error("Please ensure MySQL server is running and accessible")
            logger.error("You can start MySQL with: sudo service mysql start (Linux) or start MySQL service (Windows)")
            # Continue without database for now
    
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
        """Create database and tables if they don't exist - unified schema"""
        config_without_db = self.config.copy()
        db_name = config_without_db.pop('database')
        
        conn = None
        cursor = None
        
        try:
            conn = mysql.connector.connect(**config_without_db)
            cursor = conn.cursor()
            
            cursor.execute(f"CREATE DATABASE IF NOT EXISTS {db_name}")
            cursor.execute(f"USE {db_name}")
            
            # Create unified tickets table (shared with email bot)
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
                    FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                    INDEX idx_ticket_updates (ticket_id)
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
            
            # Create messages table
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
            
            # Create pending_approvals table (shared with email bot)
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
            
            conn.commit()
            logger.info("Database setup completed successfully")
            
        except Error as e:
            logger.error(f"Error setting up database: {e}")
            raise
        finally:
            if cursor:
                cursor.close()
            if conn and conn.is_connected():
                conn.close()

# ============================================================================
# SESSION MANAGER
# ============================================================================

class ChatSessionManager:
    """Manages chat sessions"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def create_session(self, user_id: Optional[str] = None) -> str:
        """Create a new chat session"""
        session_id = str(uuid.uuid4())
        
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_sessions (session_id, session_type, user_id, user_email)
                VALUES (%s, 'chat', %s, %s)
            """, (session_id, user_id or f'user_{uuid.uuid4().hex[:8]}', 
                  f'{user_id or uuid.uuid4().hex[:8]}@chat.local'))
            conn.commit()
            
        logger.info(f"Created new chat session: {session_id}")
        return session_id
    
    def get_session(self, session_id: str) -> Optional[Dict]:
        """Get session details"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT * FROM chat_sessions
                WHERE session_id = %s
            """, (session_id,))
            return cursor.fetchone()
    
    def save_message(self, session_id: str, sender_type: str, 
                    content: str, metadata: Optional[Dict] = None):
        """Save a chat message"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO chat_messages 
                (session_id, sender_type, message_content, message_metadata, source)
                VALUES (%s, %s, %s, %s, 'chat')
            """, (session_id, sender_type, content, 
                  json.dumps(metadata) if metadata else None))
            
            cursor.execute("""
                UPDATE chat_sessions 
                SET last_activity = NOW()
                WHERE session_id = %s
            """, (session_id,))
            
            conn.commit()
            logger.debug(f"Saved message for session {session_id}")
    
    def get_messages(self, session_id: str, limit: int = 50) -> List[Dict]:
        """Get chat messages for a session"""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                
                cursor.execute("""
                    SELECT message_id, sender_type, message_content, 
                           message_metadata, timestamp
                    FROM chat_messages
                    WHERE session_id = %s
                    ORDER BY timestamp DESC
                    LIMIT %s
                """, (session_id, limit))
                
                messages = cursor.fetchall()
                
                for msg in messages:
                    if msg.get('message_metadata'):
                        try:
                            msg['message_metadata'] = json.loads(msg['message_metadata'])
                        except:
                            pass
                
                return list(reversed(messages))
                
        except Exception as e:
            logger.error(f"Error in get_messages: {e}")
            logger.error(f"Session ID: {session_id}")
            raise
    
    def save_context(self, session_id: str, context_type: str, 
                    context_data: Dict) -> None:
        """Save conversation context"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor()
            cursor.execute("""
                INSERT INTO conversation_context 
                (session_id, context_type, context_data)
                VALUES (%s, %s, %s)
            """, (session_id, context_type, json.dumps(context_data)))
            conn.commit()
            logger.debug(f"Saved context for session {session_id}")
    
    def get_latest_context(self, session_id: str, context_type: str) -> Optional[Dict]:
        """Get the latest context of a specific type"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT context_data 
                FROM conversation_context
                WHERE session_id = %s AND context_type = %s
                ORDER BY created_at DESC
                LIMIT 1
            """, (session_id, context_type))
            
            result = cursor.fetchone()
            if result and result['context_data']:
                return json.loads(result['context_data'])
            return None

# ============================================================================
# CHAT TICKET MANAGER
# ============================================================================

class ChatTicketManager:
    """Manages hiring tickets - unified with email bot"""
    
    def __init__(self, db_manager: DatabaseManager):
        self.db_manager = db_manager
    
    def generate_ticket_id(self) -> str:
        """Generate a unique ticket ID"""
        return hashlib.md5(f"{datetime.now()}_{secrets.token_hex(4)}".encode()).hexdigest()[:10]
    
    def create_ticket(self, session_id: str, sender_email: str, 
                     details: Dict[str, str]) -> Tuple[str, bool]:
        """Create a new ticket"""
        ticket_id = self.generate_ticket_id()
        
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Create ticket with 'chat' as source
                # Use sender_email for both user_id and sender to ensure proper filtering
                cursor.execute("""
                    INSERT INTO tickets (ticket_id, source, session_id, user_id, sender, subject)
                    VALUES (%s, 'chat', %s, %s, %s, %s)
                """, (ticket_id, session_id, sender_email, sender_email, 
                      details.get('job_title', 'Job Posting')))
                
                # Insert details
                for field_name, field_value in details.items():
                    if field_value and field_value != "NOT_FOUND":
                        cursor.execute("""
                            INSERT INTO ticket_details (ticket_id, field_name, field_value, is_initial, source)
                            VALUES (%s, %s, %s, TRUE, 'chat')
                        """, (ticket_id, field_name, field_value))
                        
                        # Add to history
                        cursor.execute("""
                            INSERT INTO ticket_history 
                            (ticket_id, field_name, old_value, new_value, changed_by, change_type, source)
                            VALUES (%s, %s, NULL, %s, %s, 'create', 'chat')
                        """, (ticket_id, field_name, field_value, sender_email))
                
                conn.commit()
                logger.info(f"Created ticket {ticket_id} from chat")
                return ticket_id, True
            
        except Exception as e:
            logger.error(f"Error creating ticket: {e}")
            return None, False
    
    def update_ticket(self, ticket_id: str, user_id: str, 
                     updates: Dict[str, str]) -> Tuple[bool, str]:
        """Update ticket details"""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if ticket exists and user has permission
                cursor.execute("""
                    SELECT user_id, status, source FROM tickets WHERE ticket_id = %s
                """, (ticket_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False, "Ticket not found"
                
                # Allow updates if it's from chat source OR user created it
                if result[2] == 'chat':
                    # Chat tickets can be updated by any chat user
                    pass
                elif result[0] != user_id:
                    return False, "You don't have permission to update this ticket"
                
                if result[1] == 'terminated':
                    return False, "Cannot update a terminated ticket"
                
                # Update each field
                updated_fields = []
                for field_name, new_value in updates.items():
                    if field_name in Config.REQUIRED_HIRING_DETAILS and new_value:
                        # Get current value
                        cursor.execute("""
                            SELECT field_value FROM ticket_details
                            WHERE ticket_id = %s AND field_name = %s
                            ORDER BY created_at DESC
                            LIMIT 1
                        """, (ticket_id, field_name))
                        
                        old_value_result = cursor.fetchone()
                        old_value = old_value_result[0] if old_value_result else None
                        
                        if old_value != new_value:
                            # Insert new value
                            cursor.execute("""
                                INSERT INTO ticket_details (ticket_id, field_name, field_value, is_initial, source)
                                VALUES (%s, %s, %s, FALSE, 'chat')
                            """, (ticket_id, field_name, new_value))
                            
                            # Add to history
                            cursor.execute("""
                                INSERT INTO ticket_history 
                                (ticket_id, field_name, old_value, new_value, changed_by, source)
                                VALUES (%s, %s, %s, %s, %s, 'chat')
                            """, (ticket_id, field_name, old_value, new_value, user_id))
                            
                            updated_fields.append(field_name)
                
                # Update ticket timestamp
                cursor.execute("""
                    UPDATE tickets 
                    SET last_updated = NOW(), status = 'updated'
                    WHERE ticket_id = %s
                """, (ticket_id,))
                
                # Add to ticket_updates table
                if updated_fields:
                    cursor.execute("""
                        INSERT INTO ticket_updates (ticket_id, updated_fields, update_source)
                        VALUES (%s, %s, 'chat')
                    """, (ticket_id, json.dumps(updates)))
                
                conn.commit()
                
                if updated_fields:
                    return True, f"Updated fields: {', '.join(updated_fields)}"
                else:
                    return True, "No changes were made"
                    
        except Exception as e:
            logger.error(f"Error updating ticket: {e}")
            return False, f"Error updating ticket: {str(e)}"
    
    def get_user_tickets(self, user_id: str) -> List[Dict]:
        """Get all tickets for a user (including email tickets)"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            cursor.execute("""
                SELECT t.*, td.field_value as job_title
                FROM tickets t
                LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                    AND td.field_name = 'job_title' AND td.is_initial = TRUE
                WHERE t.user_id = %s OR t.sender = %s
                ORDER BY t.created_at DESC
            """, (user_id, user_id))
            return cursor.fetchall()
    
    def get_ticket_details(self, ticket_id: str) -> Optional[Dict]:
        """Get details of a specific ticket"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            cursor.execute("""
                SELECT * FROM tickets WHERE ticket_id = %s
            """, (ticket_id,))
            ticket = cursor.fetchone()
            
            if not ticket:
                return None
            
            # Get latest details
            cursor.execute("""
                SELECT DISTINCT field_name,
                       (SELECT field_value 
                        FROM ticket_details td2 
                        WHERE td2.ticket_id = td1.ticket_id 
                        AND td2.field_name = td1.field_name 
                        ORDER BY td2.created_at DESC 
                        LIMIT 1) as field_value
                FROM ticket_details td1
                WHERE ticket_id = %s
            """, (ticket_id,))
            
            details = {}
            for row in cursor.fetchall():
                details[row['field_name']] = row['field_value']
            
            ticket['details'] = details
            return ticket
    
    def terminate_ticket(self, ticket_id: str, user_id: str, 
                        reason: str = "User requested termination") -> Tuple[bool, str]:
        """Terminate a ticket"""
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                
                # Check if ticket exists and user has permission
                cursor.execute("""
                    SELECT user_id, status, source FROM tickets WHERE ticket_id = %s
                """, (ticket_id,))
                result = cursor.fetchone()
                
                if not result:
                    return False, "Ticket not found"
                
                # Allow termination if user created it OR if it's from chat source
                if result[0] != user_id and result[2] != 'chat':
                    return False, "You don't have permission to terminate this ticket"
                
                if result[1] == 'terminated':
                    return False, "Ticket is already terminated"
                
                # Terminate the ticket
                cursor.execute("""
                    UPDATE tickets 
                    SET status = 'terminated',
                        terminated_at = NOW(),
                        terminated_by = %s,
                        termination_reason = %s,
                        approval_status = 'terminated'
                    WHERE ticket_id = %s
                """, (user_id, reason, ticket_id))
                
                # Add to history
                cursor.execute("""
                    INSERT INTO ticket_history 
                    (ticket_id, field_name, old_value, new_value, changed_by, change_type, source)
                    VALUES (%s, 'status', %s, 'terminated', %s, 'terminate', 'chat')
                """, (ticket_id, result[1], user_id))
                
                conn.commit()
                return True, "Ticket terminated successfully"
                
        except Exception as e:
            logger.error(f"Error terminating ticket: {e}")
            return False, f"Error terminating ticket: {str(e)}"
    
    def get_all_tickets_summary(self) -> Dict[str, Any]:
        """Get summary of all tickets in the system"""
        with self.db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            # Get counts by source and status
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN source = 'email' THEN 1 ELSE 0 END) as email_tickets,
                    SUM(CASE WHEN source = 'chat' THEN 1 ELSE 0 END) as chat_tickets,
                    SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) as approved,
                    SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'terminated' THEN 1 ELSE 0 END) as terminated_count
                FROM tickets
            """)
            
            summary = cursor.fetchone()
            
            # Rename the field to match what we expect
            summary['terminated'] = summary.pop('terminated_count')
            
            # Get recent approved tickets
            cursor.execute("""
                SELECT t.ticket_id, t.source, td.field_value as job_title
                FROM tickets t
                LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                    AND td.field_name = 'job_title' AND td.is_initial = TRUE
                WHERE t.approval_status = 'approved'
                ORDER BY t.approved_at DESC
                LIMIT 5
            """)
            
            summary['recent_approved'] = cursor.fetchall()
            
            return summary

# ============================================================================
# AI AGENTS (USING OPENAI)
# ============================================================================

class LanguageDetectorAgent(AssistantAgent):
    """Agent for detecting non-English messages"""
    
    def __init__(self):
        system_message = """You are a language detector. Analyze the message and return a JSON object.

Return JSON in this exact format:
{
    "is_english": true/false,
    "detected_language": "language_name",
    "confidence": 0.0-1.0,
    "has_mixed_languages": true/false
}

Guidelines:
- Single words like city names (Pune, Mumbai, Delhi, etc.) should be considered English
- Common Indian place names are acceptable as English
- Technical terms, company names, and proper nouns should be considered English
- Only mark as non-English if the message contains actual non-English words or scripts
- Be lenient with single-word responses - they're usually names or places
- Look for non-English scripts (Devanagari, Arabic, Chinese, etc.)
- Check for mixed language usage (Hinglish, etc.)

Examples that should be marked as ENGLISH (is_english: true):
- "Pune" (city name)
- "Mumbai" (city name)  
- "5 LPA" (salary notation)
- "Kumar" (name)
- "System Engineer" (job title)
- Any single English word

Examples that should be marked as NON-ENGLISH:
- "नमस्ते" (Hindi greeting)
- "કેમ છો" (Gujarati)
- "Bonjour comment allez-vous" (French)
- "मुझे नौकरी चाहिए" (Hindi sentence)

IMPORTANT: Return ONLY the JSON object, no other text."""
        
        super().__init__(
            name="LanguageDetector",
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

class ChatClassifierAgent(AssistantAgent):
    """Agent for classifying chat messages"""
    
    def __init__(self):
        system_message = """You are a chat message classifier. Analyze the user's message and return a JSON object with the classification.

Return JSON in this exact format:
{
    "intent": "hiring|termination|question|greeting|status_check|help|approval|update",
    "is_hiring_related": true/false,
    "has_complete_info": true/false,
    "ticket_id": "extracted_id_or_null",
    "confidence": 0.0-1.0
}

Intent descriptions:
- hiring: User wants to post a new job OR is providing job details
- termination: User wants to cancel/close/terminate a job posting
- question: User has a general question about the system
- greeting: Simple greeting
- status_check: User wants to check status of their tickets/jobs
- help: User asks for help or guidance
- approval: User wants to approve a ticket
- update: User wants to update/modify an existing ticket

For ticket_id: Look for 10-character alphanumeric IDs
IMPORTANT: Return ONLY the JSON object, no other text."""
        
        super().__init__(
            name="ChatClassifier",
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

class ChatResponseAgent(AssistantAgent):
    """Agent for generating chat responses"""
    
    def __init__(self):
        system_message = """You are a friendly hiring assistant chatbot. Generate helpful, conversational responses.

Guidelines:
- Be warm and professional
- Use clear, simple language
- Guide users step by step
- Use emojis sparingly (👋 ✅ 🎉 📝 etc.)
- Ask for one piece of information at a time
- Keep responses concise

When asking for job details:
- Job title: "What position are you looking to fill?"
- Location: "Where will this position be based?"
- Experience: "How many years of experience are you looking for?"
- Salary: "What's the salary range for this position?"
- Job description: "Can you provide a brief description of the role?"
- Skills: "What key skills should candidates have?"
- Type: "Is this Full-time, Part-time, or Contract?"
- Deadline: "When is the application deadline?"

Always maintain a helpful, encouraging tone."""
        
        super().__init__(
            name="ChatResponder",
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

class HiringDetailsExtractorAgent(AssistantAgent):
    """Agent for extracting hiring details"""
    
    def __init__(self):
        system_message = """You are a hiring details extractor. Extract job posting details from the conversation.

Return ONLY a JSON object with these fields:
{
    "job_title": "position name or NOT_FOUND",
    "location": "city/location or NOT_FOUND",
    "experience_required": "years of experience or NOT_FOUND",
    "salary_range": "salary information or NOT_FOUND",
    "job_description": "description or NOT_FOUND",
    "required_skills": "skills list or NOT_FOUND",
    "employment_type": "Full-time/Part-time/Contract or NOT_FOUND",
    "deadline": "application deadline or NOT_FOUND"
}

CRITICAL: Only extract information EXPLICITLY stated by the user. Use "NOT_FOUND" for missing fields.
Return ONLY valid JSON, no other text."""
        
        super().__init__(
            name="DetailsExtractor",
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

class UpdateDetailsExtractorAgent(AssistantAgent):
    """Agent for extracting update details"""
    
    def __init__(self):
        system_message = """You are an update details extractor. Extract what fields the user wants to update.

Return ONLY a JSON object with fields they want to update:
{
    "job_title": "new value or null",
    "location": "new value or null",
    "experience_required": "new value or null",
    "salary_range": "new value or null",
    "job_description": "new value or null",
    "required_skills": "new value or null",
    "employment_type": "new value or null",
    "deadline": "new value or null"
}

Only include fields that the user explicitly wants to update.
Return ONLY valid JSON, no other text."""
        
        super().__init__(
            name="UpdateExtractor",
            system_message=system_message,
            llm_config=llm_config,
            human_input_mode="NEVER"
        )

# ============================================================================
# MAIN CHAT BOT HANDLER
# ============================================================================

class ChatBotHandler:
    """Main chat bot handler that coordinates everything"""
    
    def __init__(self):
        self.db_manager = DatabaseManager()
        self.session_manager = ChatSessionManager(self.db_manager)
        self.ticket_manager = ChatTicketManager(self.db_manager)
        
        # Initialize AI agents
        self.language_detector = LanguageDetectorAgent()
        self.classifier = ChatClassifierAgent()
        self.responder = ChatResponseAgent()
        self.extractor = HiringDetailsExtractorAgent()
        self.update_extractor = UpdateDetailsExtractorAgent()
        
        # Test database connection
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("SELECT 1")
                result = cursor.fetchone()
                logger.info("Database connection test successful")
        except Exception as e:
            logger.error(f"Database connection test failed: {e}")
            logger.warning("Continuing without database functionality")
        
        # Test OpenAI connection
        self._test_openai_connection()
    
    def _test_openai_connection(self):
        """Test OpenAI API connection"""
        try:
            test_response = self.responder.generate_reply(
                messages=[{"content": "Say 'OpenAI connection successful!'", "role": "user"}]
            )
            logger.info(f"OpenAI API test successful: {test_response}")
        except Exception as e:
            logger.error(f"OpenAI API test failed: {e}")
            raise ValueError(f"Failed to connect to OpenAI API: {e}")
    
    def start_session(self, user_id: Optional[str] = None) -> Dict:
        """Start a new chat session"""
        session_id = self.session_manager.create_session(user_id)
        
        welcome_message = ("Hello! 👋 I'm your hiring assistant. I can help you:\n\n"
                          "• Post new job openings\n"
                          "• Check status of your postings (including email submissions)\n"
                          "• Update existing tickets\n"
                          "• Terminate job postings\n"
                          "• View all jobs in the system\n\n"
                          "What would you like to do today?")
        
        self.session_manager.save_message(session_id, "assistant", welcome_message)
        
        return {
            'session_id': session_id,
            'user_id': user_id or f'user_{uuid.uuid4().hex[:8]}',
            'message': welcome_message
        }
    
    def _contains_non_english_script(self, text: str) -> bool:
        """Check if text contains non-English scripts"""
        # Check for various non-Latin scripts
        non_english_ranges = [
            (0x0900, 0x097F),  # Devanagari
            (0x0A80, 0x0AFF),  # Gujarati
            (0x0980, 0x09FF),  # Bengali
            (0x0B80, 0x0BFF),  # Tamil
            (0x0C00, 0x0C7F),  # Telugu
            (0x0A00, 0x0A7F),  # Punjabi
            (0x4E00, 0x9FFF),  # Chinese
            (0x3040, 0x309F),  # Hiragana
            (0x30A0, 0x30FF),  # Katakana
            (0x0600, 0x06FF),  # Arabic
            (0x0E00, 0x0E7F),  # Thai
            (0xAC00, 0xD7AF),  # Korean
            (0x0400, 0x04FF),  # Cyrillic
        ]
        
        for char in text:
            code_point = ord(char)
            for start, end in non_english_ranges:
                if start <= code_point <= end:
                    return True
        return False
    
    def _quick_language_check(self, message: str) -> Optional[str]:
        """Quick check for common non-English patterns"""
        
        # First check for non-ASCII characters that indicate specific scripts
        if not message.isascii():
            # Check for specific scripts with their Unicode ranges
            for char in message:
                code_point = ord(char)
                
                # Chinese (CJK Unified Ideographs)
                if 0x4E00 <= code_point <= 0x9FFF:
                    return 'Chinese'
                # Devanagari (Hindi/Marathi)
                elif 0x0900 <= code_point <= 0x097F:
                    return 'Hindi/Marathi'
                # Gujarati
                elif 0x0A80 <= code_point <= 0x0AFF:
                    return 'Gujarati'
                # Bengali
                elif 0x0980 <= code_point <= 0x09FF:
                    return 'Bengali'
                # Tamil
                elif 0x0B80 <= code_point <= 0x0BFF:
                    return 'Tamil'
                # Telugu
                elif 0x0C00 <= code_point <= 0x0C7F:
                    return 'Telugu'
                # Punjabi
                elif 0x0A00 <= code_point <= 0x0A7F:
                    return 'Punjabi'
                # Japanese Hiragana
                elif 0x3040 <= code_point <= 0x309F:
                    return 'Japanese'
                # Japanese Katakana
                elif 0x30A0 <= code_point <= 0x30FF:
                    return 'Japanese'
                # Arabic
                elif 0x0600 <= code_point <= 0x06FF:
                    return 'Arabic'
                # Thai
                elif 0x0E00 <= code_point <= 0x0E7F:
                    return 'Thai'
                # Korean
                elif 0xAC00 <= code_point <= 0xD7AF:
                    return 'Korean'
                # Cyrillic (Russian, etc.)
                elif 0x0400 <= code_point <= 0x04FF:
                    return 'Russian'
        
        # Convert message to lowercase for pattern matching
        message_lower = message.lower().strip()
        
        # Common non-English words and phrases (check these BEFORE patterns)
        non_english_words = {
            # Spanish
            'hola': 'Spanish',
            'gracias': 'Spanish',
            'por favor': 'Spanish',
            'buenos días': 'Spanish',
            'buenas tardes': 'Spanish',
            'necesito': 'Spanish',
            'ayuda': 'Spanish',
            
            # French
            'bonjour': 'French',
            'bonsoir': 'French',
            'merci': 'French',
            'au revoir': 'French',
            's\'il vous plaît': 'French',
            'comment allez-vous': 'French',
            'je suis': 'French',
            'aide': 'French',
            
            # German
            'hallo': 'German',
            'guten tag': 'German',
            'guten morgen': 'German',
            'danke': 'German',
            'bitte': 'German',
            'auf wiedersehen': 'German',
            'wie geht\'s': 'German',
            'hilfe': 'German',
            
            # Italian
            'ciao': 'Italian',
            'buongiorno': 'Italian',
            'grazie': 'Italian',
            'prego': 'Italian',
            'arrivederci': 'Italian',
            
            # Portuguese
            'olá': 'Portuguese',
            'obrigado': 'Portuguese',
            'por favor': 'Portuguese',
            'bom dia': 'Portuguese',
            
            # Dutch
            'hoi': 'Dutch',
            'dank je': 'Dutch',
            'alsjeblieft': 'Dutch',
            
            # Russian (transliterated)
            'privet': 'Russian',
            'spasibo': 'Russian',
            'pozhaluysta': 'Russian',
        }
        
        # Check exact matches first
        if message_lower in non_english_words:
            return non_english_words[message_lower]
        
        # Check if message contains any of these phrases
        for phrase, language in non_english_words.items():
            if phrase in message_lower:
                return language
        
        # Common non-English patterns with regex
        non_english_patterns = {
            'Hindi': [
                r'नमस्ते', r'क्या हाल है', r'धन्यवाद', r'कृपया', r'मैं', r'आप',
                r'नौकरी', r'काम', r'चाहिए', r'कैसे', r'कब', r'क्यों'
            ],
            'Marathi': [
                r'नमस्कार', r'कसे आहात', r'धन्यवाद', r'कृपया', r'मी', r'तुम्ही',
                r'नोकरी', r'काम', r'पाहिजे'
            ],
            'Gujarati': [
                r'નમસ્તે', r'કેમ છો', r'આભાર', r'કૃપા કરીને', r'હું', r'તમે',
                r'નોકરી', r'કામ', r'જોઈએ'
            ],
            'Bengali': [
                r'নমস্কার', r'কেমন আছেন', r'ধন্যবাদ', r'দয়া করে', r'আমি', r'আপনি',
                r'চাকরি', r'কাজ'
            ],
            'Tamil': [
                r'வணக்கம்', r'எப்படி இருக்கிறீர்கள்', r'நன்றி', r'தயவுசெய்து',
                r'நான்', r'நீங்கள்', r'வேலை'
            ],
            'Telugu': [
                r'నమస్కారం', r'ఎలా ఉన్నారు', r'ధన్యవాదాలు', r'దయచేసి',
                r'నేను', r'మీరు', r'ఉద్యోగం'
            ],
            'Punjabi': [
                r'ਸਤ ਸ੍ਰੀ ਅਕਾਲ', r'ਕਿਵੇਂ ਹੋ', r'ਧੰਨਵਾਦ', r'ਕਿਰਪਾ ਕਰਕੇ',
                r'ਮੈਂ', r'ਤੁਸੀਂ', r'ਨੌਕਰੀ'
            ],
            'Chinese': [
                r'你好', r'谢谢', r'请', r'我', r'你', r'工作', r'招聘', r'帮助'
            ],
            'Japanese': [
                r'こんにちは', r'ありがとう', r'お願いします', r'私', r'あなた', r'仕事'
            ],
            'Arabic': [
                r'مرحبا', r'شكرا', r'من فضلك', r'أنا', r'أنت', r'عمل', r'وظيفة'
            ]
        }
        
        # Check for pattern matches
        for language, patterns in non_english_patterns.items():
            for pattern in patterns:
                if re.search(pattern, message, re.IGNORECASE | re.UNICODE):
                    return language
        
        return None
    
    def _check_language(self, message: str) -> Dict:
        """Check if the message is in English"""
        
        # Skip check for very short messages or numbers
        if len(message.strip()) < 3 or message.strip().isdigit():
            return {"is_english": True}
        
        # List of common English words and Indian city names that should be allowed
        english_exceptions = [
            # Indian cities
            'pune', 'mumbai', 'delhi', 'bangalore', 'bengaluru', 'chennai', 'kolkata',
            'hyderabad', 'ahmedabad', 'surat', 'jaipur', 'lucknow', 'kanpur', 'nagpur',
            'patna', 'indore', 'thane', 'bhopal', 'vadodara', 'chandigarh', 'gurgaon',
            'gurugram', 'noida', 'navi mumbai', 'nasik', 'nashik', 'faridabad', 'agra',
            'mysore', 'mysuru', 'kochi', 'cochin', 'trivandrum', 'thiruvananthapuram',
            
            # Common job-related terms
            'lpa', 'lakhs', 'crore', 'fresher', 'wfh', 'wfo', 'hybrid',
            
            # Common names (add more as needed)
            'raj', 'kumar', 'sharma', 'singh', 'patel', 'shah', 'mehta'
        ]
        
        # Check if message is a known exception
        message_lower = message.lower().strip()
        if message_lower in english_exceptions:
            return {"is_english": True}
        
        # Check if it's a single word that might be a name or place
        if len(message.split()) == 1 and len(message) < 15:
            # First check if it contains non-English scripts
            if self._contains_non_english_script(message):
                quick_result = self._quick_language_check(message)
                if quick_result:
                    return {
                        "is_english": False,
                        "detected_language": quick_result,
                        "confidence": 0.9,
                        "has_mixed_languages": False
                    }
            # Then check if it's a known non-English word (even if ASCII)
            elif message.isascii():
                quick_result = self._quick_language_check(message)
                if quick_result:
                    return {
                        "is_english": False,
                        "detected_language": quick_result,
                        "confidence": 0.9,
                        "has_mixed_languages": False
                    }
            # Default to English for other single words
            return {"is_english": True}
        
        # Quick pattern check first - this will now check Unicode properly
        quick_result = self._quick_language_check(message)
        if quick_result:
            logger.debug(f"Quick language check detected: {quick_result} for message: {message}")
            return {
                "is_english": False,
                "detected_language": quick_result,
                "confidence": 0.9,
                "has_mixed_languages": False
            }
        
        # For longer messages, use AI detection
        if len(message.split()) > 3:
            detection_response = self.language_detector.generate_reply(
                messages=[{"content": message, "role": "user"}]
            )
            
            language_info = extract_json_from_text(detection_response)
            
            if not language_info:
                # Default to assuming English if detection fails
                return {"is_english": True}
            
            logger.debug(f"AI language detection result: {language_info} for message: {message}")
            return language_info
        
        # Default to English for short responses
        return {"is_english": True}
    
    def _generate_language_reminder(self, language_info: Dict) -> Dict:
        """Generate a polite reminder to use English"""
        
        detected_language = language_info.get('detected_language', 'non-English')
        
        # Customize response based on detected language
        language_specific_greetings = {
            'Hindi': 'नमस्ते! ',
            'Hindi/Marathi': 'नमस्ते/नमस्कार! ',
            'Marathi': 'नमस्कार! ',
            'Gujarati': 'નમસ્તે! ',
            'Bengali': 'নমস্কার! ',
            'Tamil': 'வணக்கம்! ',
            'Telugu': 'నమస్కారం! ',
            'Punjabi': 'ਸਤ ਸ੍ਰੀ ਅਕਾਲ! ',
            'Spanish': '¡Hola! ',
            'French': 'Bonjour! ',
            'German': 'Hallo! ',
            'Chinese': '你好! ',
            'Japanese': 'こんにちは! ',
            'Arabic': 'مرحبا! ',
            'Thai': 'สวัสดี! ',
            'Korean': '안녕하세요! ',
            'Portuguese': 'Olá! ',
            'Italian': 'Ciao! ',
            'Russian': 'Привет! ',
            'Dutch': 'Hallo! '
        }
        
        greeting = language_specific_greetings.get(detected_language, '')
        
        response_text = f"""{greeting}I appreciate your message, but I can only assist you in English at the moment. 🌍

Please feel free to ask your question in English, and I'll be happy to help you with:
• Posting new job openings
• Checking status of your postings
• Updating existing tickets
• Any other hiring-related queries

Thank you for your understanding! 😊"""
        
        return {
            "message": response_text,
            "metadata": {
                "language_detected": detected_language,
                "is_english": False,
                "action": "language_reminder"
            }
        }
    
    def process_message(self, session_id: str, user_id: str, 
                       message: str, authenticated_user_email: Optional[str] = None) -> Dict[str, Any]:
        """Process a user message and generate response"""
        
        try:
            # Save user message
            self.session_manager.save_message(session_id, "user", message)
            
            # Check language first
            language_check = self._check_language(message)
            
            if not language_check.get('is_english', True):
                # Generate language reminder response
                response = self._generate_language_reminder(language_check)
                
                # Save assistant response
                self.session_manager.save_message(
                    session_id, "assistant", response['message'],
                    metadata=response.get('metadata')
                )
                
                return response
            
            # Continue with normal processing if English
            # Get conversation history
            history = self.session_manager.get_messages(session_id, limit=10)
            
            # Classify the message
            classification = self._classify_message(message, history)
            
            # Generate appropriate response
            response = self._generate_response(
                session_id, user_id, message, classification, history, authenticated_user_email
            )
            
            # Save assistant response
            self.session_manager.save_message(
                session_id, "assistant", response['message'],
                metadata=response.get('metadata')
            )
            
            return response
            
        except Exception as e:
            logger.error(f"Error in process_message: {str(e)}")
            logger.error(f"Session ID: {session_id}, User ID: {user_id}, Message: {message}")
            import traceback
            traceback.print_exc()
            
            error_response = {
                "message": "I apologize, but I encountered an error processing your request. Please try again.",
                "metadata": {"error": str(e)}
            }
            
            try:
                self.session_manager.save_message(
                    session_id, "assistant", error_response['message'],
                    metadata=error_response.get('metadata')
                )
            except:
                pass
                
            return error_response
    
    def _classify_message(self, message: str, history: List[Dict]) -> Dict:
        """Classify user message intent"""
        context = self._build_context(history)
        
        prompt = f"""
        Classify this message:
        
        Current message: {message}
        
        Recent conversation context:
        {context}
        """
        
        response = self.classifier.generate_reply(
            messages=[{"content": prompt, "role": "user"}]
        )
        
        classification = extract_json_from_text(response)
        
        if not classification:
            classification = {
                "intent": "question",
                "is_hiring_related": False,
                "has_complete_info": False,
                "confidence": 0.7
            }
        
        return classification
    
    def _generate_response(self, session_id: str, user_id: str, 
                          message: str, classification: Dict,
                          history: List[Dict], authenticated_user_email: Optional[str] = None) -> Dict:
        """Generate response based on intent"""
        
        intent = classification.get('intent', 'question')
        
        # Override intent based on keywords
        message_lower = message.lower()
        if 'approve' in message_lower and any(char.isdigit() or char.isalpha() for char in message_lower):
            intent = 'approval'
        elif any(phrase in message_lower for phrase in ['update ticket', 'modify ticket', 'change ticket']):
            intent = 'update'
        elif any(phrase in message_lower for phrase in ['show my tickets', 'my tickets', 'list tickets', 'all tickets', 'show all']):
            intent = 'status_check'
        elif any(phrase in message_lower for phrase in ['terminate ticket', 'close ticket', 'cancel ticket']):
            intent = 'termination'
        elif 'show ticket' in message_lower and re.search(r'[a-f0-9]{10}', message_lower):
            intent = 'show_ticket'
        
        handlers = {
            'hiring': self._handle_hiring_intent,
            'termination': self._handle_termination_intent,
            'status_check': self._handle_status_check,
            'help': self._handle_help_request,
            'greeting': self._handle_greeting,
            'question': self._handle_general_question,
            'approval': self._handle_approval_intent,
            'update': self._handle_update_intent,
            'show_ticket': self._handle_show_ticket
        }
        
        handler = handlers.get(intent, self._handle_general_question)
        
        if intent in ['hiring', 'termination', 'question', 'approval', 'update', 'show_ticket']:
            return handler(session_id, user_id, message, classification, history, authenticated_user_email)
        elif intent == 'status_check':
            return handler(user_id, message)
        elif intent in ['help', 'greeting']:
            return handler(user_id)
        else:
            return handler(session_id, user_id, message, classification, history, authenticated_user_email)
    
    def _handle_hiring_intent(self, session_id: str, user_id: str,
                             message: str, classification: Dict,
                             history: List[Dict], authenticated_user_email: Optional[str] = None) -> Dict:
        """Handle job posting intent"""
        
        # Get or create hiring context
        hiring_context = self.session_manager.get_latest_context(session_id, 'hiring_flow')
        
        # Build full conversation context
        full_context = self._build_hiring_context(history, message)
        
        # Extract details
        extraction_prompt = f"""
        Extract all job posting details from this conversation:
        
        {full_context}
        """
        
        extraction_response = self.extractor.generate_reply(
            messages=[{"content": extraction_prompt, "role": "user"}]
        )
        
        details = extract_json_from_text(extraction_response) or {}
        
        # Clean up extraction
        cleaned_details = {}
        for key, value in details.items():
            if value and value != "NOT_FOUND" and len(str(value)) > 0:
                cleaned_details[key] = value
            else:
                cleaned_details[key] = "NOT_FOUND"
        
        # Merge with existing context if available
        if hiring_context and hiring_context.get('collected_fields'):
            existing_details = hiring_context['collected_fields']
            for key, value in existing_details.items():
                if key not in cleaned_details or cleaned_details[key] == "NOT_FOUND":
                    cleaned_details[key] = value
        
        # Save context
        self.session_manager.save_context(session_id, 'hiring_flow', {
            'collected_fields': cleaned_details,
            'timestamp': datetime.now().isoformat()
        })
        
        # Check for missing fields
        missing_fields = []
        for field in Config.REQUIRED_HIRING_DETAILS:
            if field not in cleaned_details or cleaned_details.get(field) == "NOT_FOUND":
                missing_fields.append(field)
        
        if missing_fields:
            # Ask for next missing field
            field_to_ask = missing_fields[0]
            
            prompt = f"""
            The user is posting a job. Ask for the {field_to_ask.replace('_', ' ')}.
            Be friendly and conversational.
            """
            
            response_text = self.responder.generate_reply(
                messages=[{"content": prompt, "role": "user"}]
            )
            
            return {
                "message": response_text,
                "metadata": {
                    "intent": "hiring",
                    "missing_fields": missing_fields,
                    "collected_fields": cleaned_details
                }
            }
        
        # All details collected - create ticket
        # Use authenticated user email if available, otherwise use user_id
        sender_email = authenticated_user_email if authenticated_user_email else user_id
        ticket_id, success = self.ticket_manager.create_ticket(
            session_id, sender_email, cleaned_details
        )
        
        if success:
            response_text = f"""🎉 Great! I've successfully created your job posting!

**Ticket ID:** `{ticket_id}`

**Job Summary:**
• **Position:** {cleaned_details['job_title']}
• **Location:** {cleaned_details['location']}
• **Experience:** {cleaned_details['experience_required']}
• **Salary:** {cleaned_details['salary_range']}
• **Source:** Chat

Your job posting is now pending approval. Once approved, it will be visible on the website.

Is there anything else I can help you with?"""
        else:
            response_text = "I'm sorry, I encountered an error creating your ticket. Please try again."
        
        return {
            "message": response_text,
            "metadata": {
                "intent": "hiring",
                "action": "ticket_created" if success else "error",
                "ticket_id": ticket_id if success else None
            }
        }
    
    def _handle_update_intent(self, session_id: str, user_id: str,
                             message: str, classification: Dict,
                             history: List[Dict], authenticated_user_email: Optional[str] = None) -> Dict:
        """Handle ticket update requests"""
        
        # Check if we're in the middle of an update flow
        update_context = self.session_manager.get_latest_context(session_id, 'update_flow')
        
        # If we have context and user is providing update details
        if update_context and update_context.get('ticket_id'):
            ticket_id = update_context['ticket_id']
            
            # Extract what field to update from the message
            update_prompt = f"""
            The user wants to update ticket {ticket_id}.
            Current message: {message}
            
            Extract what field they want to update and the new value.
            """
            
            update_response = self.update_extractor.generate_reply(
                messages=[{"content": update_prompt, "role": "user"}]
            )
            
            updates = extract_json_from_text(update_response)
            
            if not updates:
                # Try to parse manually
                updates = {}
                message_lower = message.lower()
                
                if 'salary' in message_lower:
                    # Extract salary value
                    salary_match = re.search(r'(\d+[-–]\d+\s*(?:lpa|lakhs|l)?|\d+\s*(?:lpa|lakhs|l)?)', message_lower)
                    if salary_match:
                        updates['salary_range'] = salary_match.group(1).upper().replace('–', '-')
                
                elif 'location' in message_lower:
                    # Extract location after "to"
                    location_match = re.search(r'to\s+([a-zA-Z\s]+)', message, re.IGNORECASE)
                    if location_match:
                        updates['location'] = location_match.group(1).strip()
                
                elif 'experience' in message_lower:
                    # Extract experience
                    exp_match = re.search(r'(\d+[-–]\d+|\d+)\s*(?:years?|yrs?)?', message_lower)
                    if exp_match:
                        updates['experience_required'] = exp_match.group(1)
                
                elif 'deadline' in message_lower:
                    # Extract deadline
                    date_match = re.search(r'(\d{1,2}[-/]\d{1,2}[-/]\d{2,4})', message)
                    if date_match:
                        updates['deadline'] = date_match.group(1)
            
            if updates:
                # Perform the update
                success, message_text = self.ticket_manager.update_ticket(
                    ticket_id, user_id, updates
                )
                
                # Clear the update context
                self.session_manager.save_context(session_id, 'update_flow', {})
                
                if success:
                    response_text = f"✅ Successfully updated ticket `{ticket_id}`!\n\n{message_text}"
                else:
                    response_text = f"❌ {message_text}"
                
                return {
                    "message": response_text,
                    "metadata": {"intent": "update", "action": "completed", "ticket_id": ticket_id}
                }
            else:
                return {
                    "message": "I couldn't understand what you want to update. Please specify clearly, for example:\n• 'Change salary to 25-30 LPA'\n• 'Update location to Mumbai'\n• 'Change experience to 5 years'",
                    "metadata": {"intent": "update", "awaiting_update_details": True, "ticket_id": ticket_id}
                }
        
        # Otherwise, we need to identify the ticket first
        ticket_id = classification.get('ticket_id')
        if not ticket_id:
            match = re.search(r'[a-f0-9]{10}', message.lower())
            if match:
                ticket_id = match.group(0)
        
        if not ticket_id:
            return {
                "message": "Please provide the ticket ID you want to update. For example: 'Update ticket abc123def4'",
                "metadata": {"intent": "update", "awaiting_ticket_id": True}
            }
        
        # Get ticket details
        ticket = self.ticket_manager.get_ticket_details(ticket_id)
        
        if not ticket:
            return {
                "message": f"❌ I couldn't find ticket `{ticket_id}`. Please check the ticket ID.",
                "metadata": {"intent": "update", "error": "ticket_not_found"}
            }
        
        # Allow updates for tickets created by user OR tickets from chat source
        if ticket['source'] == 'chat':
            # Chat tickets can be updated by any chat user
            pass
        elif ticket['user_id'] != user_id and ticket['sender'] != user_id:
            return {
                "message": "❌ You don't have permission to update this ticket.",
                "metadata": {"intent": "update", "error": "permission_denied"}
            }
        
        # Save update context
        self.session_manager.save_context(session_id, 'update_flow', {
            'ticket_id': ticket_id,
            'timestamp': datetime.now().isoformat()
        })
        
        # Show current details and ask what to update
        response_text = f"""I found ticket `{ticket_id}` for **{ticket['details'].get('job_title', 'Unknown')}**.

**Current details:**
• **Location:** {ticket['details'].get('location', 'Not set')}
• **Experience:** {ticket['details'].get('experience_required', 'Not set')}
• **Salary:** {ticket['details'].get('salary_range', 'Not set')}
• **Source:** {ticket['source'].capitalize()}

What would you like to update?"""
        
        return {
            "message": response_text,
            "metadata": {"intent": "update", "ticket_id": ticket_id, "awaiting_update_details": True}
        }
    
    def _handle_termination_intent(self, session_id: str, user_id: str,
                                  message: str, classification: Dict,
                                  history: List[Dict], authenticated_user_email: Optional[str] = None) -> Dict:
        """Handle ticket termination requests"""
        
        # Extract ticket ID
        ticket_id = classification.get('ticket_id')
        if not ticket_id:
            match = re.search(r'[a-f0-9]{10}', message.lower())
            if match:
                ticket_id = match.group(0)
        
        if ticket_id:
            success, message_text = self.ticket_manager.terminate_ticket(
                ticket_id, user_id, "User requested termination via chat"
            )
            
            if success:
                response_text = f"✅ I've successfully terminated ticket `{ticket_id}`. The job posting has been removed."
            else:
                response_text = f"❌ {message_text}"
        else:
            response_text = "Please provide the ticket ID you want to terminate. For example: 'Terminate ticket abc123def4'"
        
        return {
            "message": response_text,
            "metadata": {"intent": "termination", "ticket_id": ticket_id}
        }
    
    def _handle_status_check(self, user_id: str, message: str = "") -> Dict:
        """Handle status check requests"""
        tickets = self.ticket_manager.get_user_tickets(user_id)
        
        # Check if user wants to see all tickets in the system
        show_all = any(phrase in message.lower() for phrase in ['all tickets', 'show all', 'all jobs'])
        
        if show_all:
            summary = self.ticket_manager.get_all_tickets_summary()
            response_parts = [f"**System Overview:**"]
            response_parts.append(f"• Total Tickets: {summary['total']}")
            response_parts.append(f"• From Email: {summary['email_tickets']}")
            response_parts.append(f"• From Chat: {summary['chat_tickets']}")
            response_parts.append(f"• Approved (Live on Website): {summary['approved']}")
            response_parts.append(f"• Pending Approval: {summary['pending']}")
            response_parts.append(f"• Terminated: {summary['terminated']}")
            
            if summary['recent_approved']:
                response_parts.append("\n**Recently Approved Jobs (Visible on Website):**")
                for job in summary['recent_approved']:
                    response_parts.append(f"• `{job['ticket_id']}` - {job['job_title'] or 'Unknown'} (Source: {job['source']})")
            
            # Add all active tickets
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor(dictionary=True)
                cursor.execute("""
                    SELECT t.ticket_id, t.source, t.approval_status, t.sender,
                           td.field_value as job_title
                    FROM tickets t
                    LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                        AND td.field_name = 'job_title' AND td.is_initial = TRUE
                    WHERE t.status != 'terminated'
                    ORDER BY t.created_at DESC
                    LIMIT 20
                """)
                all_active = cursor.fetchall()
                
                if all_active:
                    response_parts.append("\n**All Active Tickets:**")
                    for ticket in all_active:
                        status_emoji = "✅" if ticket['approval_status'] == 'approved' else "⏳"
                        response_parts.append(
                            f"• {status_emoji} `{ticket['ticket_id']}` - {ticket['job_title'] or 'Unknown'} "
                            f"(Source: {ticket['source']}, By: {ticket['sender'].split('@')[0]})"
                        )
            
            response_text = "\n".join(response_parts)
        elif not tickets:
            response_text = "You haven't posted any jobs yet. Would you like to create your first job posting?"
        else:
            active_tickets = [t for t in tickets if t['status'] != 'terminated']
            
            response_parts = ["Here's a summary of your job postings:\n"]
            
            if active_tickets:
                response_parts.append("**📋 Active Postings:**")
                for ticket in active_tickets:
                    status_emoji = "✅" if ticket['approval_status'] == 'approved' else "⏳"
                    source_label = f" ({ticket['source']})" if ticket.get('source') else ""
                    response_parts.append(
                        f"• {status_emoji} `{ticket['ticket_id']}` - {ticket['job_title'] or 'Untitled'}{source_label}"
                    )
            
            response_text = "\n".join(response_parts)
        
        return {
            "message": response_text,
            "metadata": {"intent": "status_check"}
        }
    
    def _handle_help_request(self, user_id: str) -> Dict:
        """Handle help requests"""
        response_text = """I'm here to help! Here's what I can do:

**📝 Post a New Job**
Just say "I want to post a job" and I'll guide you through the process.

**📊 Check Your Postings**
Say "Show my tickets" to see all your job postings (including those from email).

**✏️ Update a Posting**
Say "Update ticket [ID]" to modify a job posting.

**❌ Terminate a Posting**
Say "Terminate ticket [ID]" to close a job posting.

**🌐 View All Jobs**
Say "Show all tickets" to see all jobs in the system.

What would you like to do?"""
        
        return {
            "message": response_text,
            "metadata": {"intent": "help"}
        }
    
    def _handle_greeting(self, user_id: str) -> Dict:
        """Handle greetings"""
        return {
            "message": "Hello! 👋 I'm ready to help you with your hiring needs. What would you like to do today?",
            "metadata": {"intent": "greeting"}
        }
    
    def _handle_general_question(self, session_id: str, user_id: str,
                                message: str, classification: Dict,
                                history: List[Dict], authenticated_user_email: Optional[str] = None) -> Dict:
        """Handle general questions"""
        context = self._build_context(history)
        
        prompt = f"""
        The user has asked a question. Provide a helpful response.
        
        Question: {message}
        Context: {context}
        
        Remember: We handle job postings from both chat and email sources.
        """
        
        response_text = self.responder.generate_reply(
            messages=[{"content": prompt, "role": "user"}]
        )
        
        return {
            "message": response_text,
            "metadata": {"intent": "question"}
        }
    
    def _handle_approval_intent(self, session_id: str, user_id: str,
                               message: str, classification: Dict,
                               history: List[Dict], authenticated_user_email: Optional[str] = None) -> Dict:
        """Handle ticket approval requests - HR users can approve, others get redirected"""
        
        # Check if user is HR (has authenticated email) or debug mode is enabled
        is_hr_user = authenticated_user_email is not None
        
        if not is_hr_user and not Config.DEBUG_MODE:
            return {
                "message": "Ticket approval is handled by HR administrators through the admin panel. Please contact your HR team for approval.",
                "metadata": {"intent": "approval", "debug_mode": False, "hr_required": True}
            }
        
        # Extract ticket ID
        ticket_id = classification.get('ticket_id')
        if not ticket_id:
            match = re.search(r'[a-f0-9]{10}', message.lower())
            if match:
                ticket_id = match.group(0)
        
        if not ticket_id:
            return {
                "message": "Please provide a ticket ID to approve. For example: 'approve ticket c8a5325ded'",
                "metadata": {"intent": "approval", "error": "no_ticket_id"}
            }
        
        # Get ticket details first to show what we're approving
        ticket = self.ticket_manager.get_ticket_details(ticket_id)
        
        if not ticket:
            return {
                "message": f"❌ I couldn't find ticket `{ticket_id}`. Please check the ticket ID.",
                "metadata": {"intent": "approval", "error": "ticket_not_found"}
            }
        
        # Check if ticket is already approved
        if ticket['approval_status'] == 'approved':
            return {
                "message": f"✅ Ticket `{ticket_id}` is already approved!",
                "metadata": {"intent": "approval", "status": "already_approved", "ticket_id": ticket_id}
            }
        
        # Show ticket details before approval
        details = ticket.get('details', {})
        approval_message = f"""**Approving Ticket: `{ticket_id}`**

**Job Details:**
• **Position:** {details.get('job_title', 'Not specified')}
• **Location:** {details.get('location', 'Not specified')}
• **Experience:** {details.get('experience_required', 'Not specified')}
• **Salary:** {details.get('salary_range', 'Not specified')}
• **Type:** {details.get('employment_type', 'Not specified')}
• **Deadline:** {details.get('deadline', 'Not specified')}

**Description:** {details.get('job_description', 'Not specified')}
**Required Skills:** {details.get('required_skills', 'Not specified')}

**Approved by:** {authenticated_user_email or 'Debug Mode'}

✅ **Ticket has been approved and will now be visible on the website!**"""
        
        # Approve the ticket
        try:
            with self.db_manager.get_connection() as conn:
                cursor = conn.cursor()
                cursor.execute("""
                    UPDATE tickets 
                    SET approval_status = 'approved', 
                        approved = TRUE,
                        approved_at = NOW()
                    WHERE ticket_id = %s
                """, (ticket_id,))
                conn.commit()
            
            return {
                "message": approval_message,
                "metadata": {"intent": "approval", "action": "approved", "ticket_id": ticket_id, "approved_by": authenticated_user_email}
            }
            
        except Exception as e:
            return {
                "message": f"❌ Error approving ticket: {str(e)}",
                "metadata": {"intent": "approval", "error": str(e)}
            }
    
    def _handle_show_ticket(self, session_id: str, user_id: str,
                           message: str, classification: Dict,
                           history: List[Dict], authenticated_user_email: Optional[str] = None) -> Dict:
        """Handle show ticket details request"""
        
        # Extract ticket ID
        ticket_id = None
        match = re.search(r'[a-f0-9]{10}', message.lower())
        if match:
            ticket_id = match.group(0)
        
        if not ticket_id:
            return {
                "message": "Please provide a ticket ID. For example: 'show ticket abc123def4'",
                "metadata": {"intent": "show_ticket", "error": "no_ticket_id"}
            }
        
        # Get ticket details
        ticket = self.ticket_manager.get_ticket_details(ticket_id)
        
        if not ticket:
            return {
                "message": f"❌ I couldn't find ticket `{ticket_id}`. Please check the ticket ID.",
                "metadata": {"intent": "show_ticket", "error": "ticket_not_found"}
            }
        
        # Format ticket details
        details = ticket.get('details', {})
        
        status_emoji = "✅" if ticket['approval_status'] == 'approved' else "⏳"
        
        response_text = f"""**Ticket Details: `{ticket_id}`**
        
{status_emoji} **Status:** {ticket['approval_status'].capitalize()} ({ticket['status']})
**Source:** {ticket['source'].capitalize()}
**Created:** {ticket['created_at'].strftime('%Y-%m-%d %H:%M') if ticket.get('created_at') else 'Unknown'}

**Job Information:**
• **Position:** {details.get('job_title', 'Not specified')}
• **Location:** {details.get('location', 'Not specified')}
• **Experience:** {details.get('experience_required', 'Not specified')}
• **Salary:** {details.get('salary_range', 'Not specified')}
• **Type:** {details.get('employment_type', 'Not specified')}
• **Deadline:** {details.get('deadline', 'Not specified')}

**Description:** {details.get('job_description', 'Not specified')}
**Required Skills:** {details.get('required_skills', 'Not specified')}"""
        
        return {
            "message": response_text,
            "metadata": {"intent": "show_ticket", "ticket_id": ticket_id}
        }
    
    def _build_context(self, history: List[Dict]) -> str:
        """Build conversation context string"""
        context_parts = []
        for msg in history[-5:]:  # Last 5 messages
            sender = "User" if msg['sender_type'] == 'user' else "Assistant"
            context_parts.append(f"{sender}: {msg['message_content']}")
        return "\n".join(context_parts)
    
    def _build_hiring_context(self, history: List[Dict], current_message: str) -> str:
        """Build context for hiring detail extraction"""
        messages = []
        for msg in history:
            if msg['sender_type'] == 'user':
                messages.append(f"User: {msg['message_content']}")
            elif msg['sender_type'] == 'assistant':
                messages.append(f"Assistant: {msg['message_content']}")
        messages.append(f"User: {current_message}")
        return "\n".join(messages)

# ============================================================================
# UTILITY FUNCTIONS
# ============================================================================

def extract_json_from_text(text: str) -> Optional[Dict]:
    """Extract JSON from text that might contain other content"""
    if not text:
        return None
    
    try:
        # Try direct parsing
        return json.loads(text.strip())
    except:
        # Try to find JSON in the text
        start = text.find('{')
        end = text.rfind('}')
        if start >= 0 and end > start:
            try:
                return json.loads(text[start:end+1])
            except:
                pass
    return None

def parse_and_validate_deadline(deadline_str: str) -> Tuple[bool, str, Optional[datetime]]:
    """Parse and validate deadline date string"""
    try:
        # Common date formats
        date_formats = [
            '%d-%m-%Y',
            '%d/%m/%Y',
            '%Y-%m-%d',
            '%d-%m-%y',
            '%d/%m/%y',
        ]
        
        parsed_date = None
        deadline_clean = deadline_str.strip()
        
        for fmt in date_formats:
            try:
                parsed_date = datetime.strptime(deadline_clean, fmt)
                break
            except ValueError:
                continue
        
        if parsed_date is None:
            return False, "Please provide the deadline in DD-MM-YYYY format.", None
        
        # Check if date is in the future
        if parsed_date <= datetime.now():
            return False, "The deadline must be in the future.", None
        
        # Format the date
        formatted_date = parsed_date.strftime('%d-%m-%Y')
        return True, formatted_date, parsed_date
        
    except Exception as e:
        return False, "Invalid date format. Please use DD-MM-YYYY.", None

# ============================================================================
# DISPLAY FUNCTIONS
# ============================================================================

def show_system_status(db_manager: DatabaseManager):
    """Display system status"""
    print("\n" + "="*60)
    print("UNIFIED SYSTEM STATUS")
    print("="*60)
    
    try:
        with db_manager.get_connection() as conn:
            cursor = conn.cursor(dictionary=True)
            
            # Get overall statistics
            cursor.execute("""
                SELECT 
                    COUNT(*) as total,
                    SUM(CASE WHEN source = 'email' THEN 1 ELSE 0 END) as email_tickets,
                    SUM(CASE WHEN source = 'chat' THEN 1 ELSE 0 END) as chat_tickets,
                    SUM(CASE WHEN approval_status = 'approved' THEN 1 ELSE 0 END) as approved,
                    SUM(CASE WHEN approval_status = 'pending' THEN 1 ELSE 0 END) as pending,
                    SUM(CASE WHEN status = 'terminated' THEN 1 ELSE 0 END) as terminated
                FROM tickets
            """)
            
            stats = cursor.fetchone()
            
            print(f"\nTotal Tickets: {stats['total']}")
            print(f"  - From Email: {stats['email_tickets']}")
            print(f"  - From Chat: {stats['chat_tickets']}")
            print(f"  - Approved: {stats['approved']}")
            print(f"  - Pending: {stats['pending']}")
            print(f"  - Terminated: {stats['terminated']}")
            
            # Show approved jobs
            print("\nApproved Jobs (visible on website):")
            cursor.execute("""
                SELECT t.ticket_id, t.source, td.field_value as job_title
                FROM tickets t
                LEFT JOIN ticket_details td ON t.ticket_id = td.ticket_id 
                    AND td.field_name = 'job_title' AND td.is_initial = TRUE
                WHERE t.approval_status = 'approved'
                ORDER BY t.approved_at DESC
                LIMIT 10
            """)
            
            approved_jobs = cursor.fetchall()
            if approved_jobs:
                for job in approved_jobs:
                    print(f"  - {job['ticket_id']} | {job['job_title'] or 'Unknown'} | Source: {job['source']}")
            else:
                print("  - No approved jobs")
                
    except Exception as e:
        print(f"Error displaying status: {e}")

# ============================================================================
# MAIN ENTRY POINT AND TEST FUNCTIONS
# ============================================================================

def test_chatbot():
    """Test the chatbot with sample conversations"""
    print("\n" + "="*60)
    print("TESTING CHAT BOT WITH LANGUAGE DETECTION")
    print("="*60)
    
    bot = ChatBotHandler()
    
    # Start a new session
    session_data = bot.start_session("test_user_123")
    session_id = session_data['session_id']
    user_id = session_data['user_id']
    
    print(f"\nSession started: {session_id}")
    print(f"Bot: {session_data['message']}")
    
    # Test cases
    test_messages = [
        # Test non-English messages
        "नमस्ते, मुझे एक नौकरी पोस्ट करनी है",  # Hindi
        "Hola, necesito publicar un trabajo",  # Spanish
        "કેમ છો? મારે નોકરી પોસ્ટ કરવી છે",  # Gujarati
        "Bonjour, je veux poster un emploi",  # French
        "你好，我想发布一个职位",  # Chinese
        
        # Test English messages
        "Hello, I want to post a job",
        "Software Engineer",
        "Mumbai",
        "5-7 years",
        "25-30 LPA",
        "Looking for a senior software engineer with Python and Django experience",
        "Python, Django, REST APIs, PostgreSQL",
        "Full-time",
        "31-01-2025",
        
        # Test other features
        "show my tickets",
        "update ticket",  # This will fail without a ticket ID
        "কাজের তালিকা দেখান",  # Bengali - "show job list"
        "help",
        "مرحبا",  # Arabic greeting
    ]
    
    for message in test_messages:
        print(f"\n{'='*40}")
        print(f"User: {message}")
        
        response = bot.process_message(session_id, user_id, message)
        print(f"Bot: {response['message'][:200]}...")  # Show first 200 chars
        
        if response.get('metadata'):
            print(f"Metadata: {response['metadata']}")
        
        import time
        time.sleep(0.5)  # Small delay between messages

def main():
    """Main entry point for the chat bot"""
    print("\n" + "="*60)
    print("AI CHAT BOT WITH LANGUAGE DETECTION")
    print("="*60)
    
    try:
        # Initialize the bot
        bot = ChatBotHandler()
        
        # Show system status
        show_system_status(bot.db_manager)
        
        # Run test
        print("\nRunning test conversation...")
        test_chatbot()
        
        print("\n" + "="*60)
        print("Chat bot is ready for integration!")
        print("="*60)
        
    except Exception as e:
        print(f"\nError initializing chat bot: {e}")
        import traceback
        traceback.print_exc()

# ============================================================================
# EXPORT
# ============================================================================

__all__ = ['ChatBotHandler', 'Config', 'show_system_status', 'main']

if __name__ == "__main__":
    main()