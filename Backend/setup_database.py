#!/usr/bin/env python3
"""
Database Setup Script for Candidate Portal
Creates all required tables for the complete hiring bot system
"""

import mysql.connector
from mysql.connector import Error
import logging
import sys
import os

# Add the current directory to Python path to import Config
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from ai_bot3 import Config

# Setup logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

def get_db_connection():
    """Get database connection"""
    try:
        connection = mysql.connector.connect(
            host=Config.MYSQL_HOST,
            user=Config.MYSQL_USER,
            password=Config.MYSQL_PASSWORD,
            database=Config.MYSQL_DATABASE
        )
        return connection
    except Error as e:
        logger.error(f"Error connecting to MySQL: {e}")
        return None

def create_database_tables():
    """Create all required database tables"""
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return False
    
    try:
        cursor = conn.cursor()
        
        logger.info("Creating database tables...")
        
        # 1. Create users table (for HR authentication)
        logger.info("Creating users table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS users (
                id INT AUTO_INCREMENT PRIMARY KEY,
                user_id VARCHAR(255) UNIQUE NOT NULL,
                email VARCHAR(255) UNIQUE NOT NULL,
                password_hash VARCHAR(255) NOT NULL,
                first_name VARCHAR(100) NOT NULL,
                last_name VARCHAR(100) NOT NULL,
                role ENUM('hr') DEFAULT 'hr',
                phone VARCHAR(20),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                is_active BOOLEAN DEFAULT TRUE,
                INDEX idx_email (email),
                INDEX idx_user_id (user_id)
            )
        """)
        
        # 2. Create tickets table (main job posting table)
        logger.info("Creating tickets table...")
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
        
        # 3. Create ticket_details table
        logger.info("Creating ticket_details table...")
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
        
        # 4. Create ticket_updates table
        logger.info("Creating ticket_updates table...")
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
        
        # 5. Create ticket_history table
        logger.info("Creating ticket_history table...")
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
        
        # 6. Create chat_sessions table
        logger.info("Creating chat_sessions table...")
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
        
        # 7. Create chat_messages table
        logger.info("Creating chat_messages table...")
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
        
        # 8. Create conversation_context table
        logger.info("Creating conversation_context table...")
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
        
        # 9. Create pending_approvals table
        logger.info("Creating pending_approvals table...")
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
                INDEX idx_approval_token (approval_token),
                INDEX idx_ticket_approval (ticket_id)
            )
        """)
        
        # 10. Create resume_applications table (for storing resume uploads)
        logger.info("Creating resume_applications table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS resume_applications (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ticket_id VARCHAR(10) NOT NULL,
                applicant_name VARCHAR(255) NOT NULL,
                applicant_email VARCHAR(255) NOT NULL,
                applicant_phone VARCHAR(20),
                filename VARCHAR(255) NOT NULL,
                file_path VARCHAR(500) NOT NULL,
                file_size INT,
                file_type VARCHAR(50),
                cover_letter TEXT,
                uploaded_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                status VARCHAR(50) DEFAULT 'pending',
                ai_score DECIMAL(5,4),
                ai_analysis JSON,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                INDEX idx_ticket_applications (ticket_id),
                INDEX idx_applicant_email (applicant_email),
                INDEX idx_uploaded_at (uploaded_at)
            )
        """)
        
        # 11. Create ai_filtering_results table
        logger.info("Creating ai_filtering_results table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS ai_filtering_results (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ticket_id VARCHAR(10) NOT NULL,
                filtering_started_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                filtering_completed_at DATETIME,
                status VARCHAR(50) DEFAULT 'running',
                total_resumes INT DEFAULT 0,
                processed_resumes INT DEFAULT 0,
                top_candidates_count INT DEFAULT 0,
                filtering_config JSON,
                results_summary JSON,
                error_message TEXT,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                INDEX idx_ticket_filtering (ticket_id),
                INDEX idx_status (status),
                INDEX idx_started_at (filtering_started_at)
            )
        """)
        
        # 12. Create job_statistics table
        logger.info("Creating job_statistics table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS job_statistics (
                id INT AUTO_INCREMENT PRIMARY KEY,
                ticket_id VARCHAR(10) NOT NULL,
                total_applications INT DEFAULT 0,
                total_resumes INT DEFAULT 0,
                ai_filtered_count INT DEFAULT 0,
                top_candidates_count INT DEFAULT 0,
                average_score DECIMAL(5,4),
                last_updated DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                statistics_data JSON,
                FOREIGN KEY (ticket_id) REFERENCES tickets(ticket_id) ON DELETE CASCADE,
                INDEX idx_ticket_stats (ticket_id),
                INDEX idx_last_updated (last_updated)
            )
        """)
        
        # 13. Create email_templates table
        logger.info("Creating email_templates table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS email_templates (
                id INT AUTO_INCREMENT PRIMARY KEY,
                template_name VARCHAR(100) UNIQUE NOT NULL,
                template_type VARCHAR(50) NOT NULL,
                subject VARCHAR(255) NOT NULL,
                body TEXT NOT NULL,
                variables JSON,
                is_active BOOLEAN DEFAULT TRUE,
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                updated_at DATETIME DEFAULT CURRENT_TIMESTAMP ON UPDATE CURRENT_TIMESTAMP,
                INDEX idx_template_name (template_name),
                INDEX idx_template_type (template_type)
            )
        """)
        
        # 14. Create system_logs table
        logger.info("Creating system_logs table...")
        cursor.execute("""
            CREATE TABLE IF NOT EXISTS system_logs (
                id INT AUTO_INCREMENT PRIMARY KEY,
                log_level VARCHAR(20) NOT NULL,
                log_message TEXT NOT NULL,
                log_source VARCHAR(100),
                user_id VARCHAR(255),
                ticket_id VARCHAR(10),
                created_at DATETIME DEFAULT CURRENT_TIMESTAMP,
                additional_data JSON,
                INDEX idx_log_level (log_level),
                INDEX idx_created_at (created_at),
                INDEX idx_user_id (user_id),
                INDEX idx_ticket_id (ticket_id)
            )
        """)
        
        # Commit all changes
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info("✅ All database tables created successfully!")
        return True
        
    except Error as e:
        logger.error(f"❌ Error creating database tables: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False

def insert_sample_data():
    """Insert sample data for testing"""
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return False
    
    try:
        cursor = conn.cursor()
        
        logger.info("Inserting sample data...")
        
        # Insert sample email templates
        cursor.execute("""
            INSERT IGNORE INTO email_templates (template_name, template_type, subject, body, variables) VALUES
            ('job_approval', 'approval', 'Job Posting Approval Required', 
             'A new job posting requires your approval. Please review and approve or reject.',
             '{"job_title": "string", "company_name": "string", "approval_link": "string"}'),
            ('application_received', 'notification', 'Application Received', 
             'Thank you for your application. We have received your resume and will review it shortly.',
             '{"applicant_name": "string", "job_title": "string", "company_name": "string"}'),
            ('top_candidates', 'notification', 'Top Candidates Identified', 
             'AI analysis has identified the top candidates for the position.',
             '{"job_title": "string", "candidate_count": "number", "analysis_summary": "string"}')
        """)
        
        # Insert sample system logs
        cursor.execute("""
            INSERT IGNORE INTO system_logs (log_level, log_message, log_source) VALUES
            ('INFO', 'Database setup completed successfully', 'setup_script'),
            ('INFO', 'Sample data inserted', 'setup_script'),
            ('INFO', 'System initialized', 'setup_script')
        """)
        
        conn.commit()
        cursor.close()
        conn.close()
        
        logger.info("✅ Sample data inserted successfully!")
        return True
        
    except Error as e:
        logger.error(f"❌ Error inserting sample data: {e}")
        if conn:
            conn.rollback()
            conn.close()
        return False

def verify_tables():
    """Verify that all tables were created successfully"""
    conn = get_db_connection()
    if not conn:
        logger.error("Failed to connect to database")
        return False
    
    try:
        cursor = conn.cursor()
        
        # List of expected tables
        expected_tables = [
            'users', 'tickets', 'ticket_details', 'ticket_updates', 
            'ticket_history', 'chat_sessions', 'chat_messages', 
            'conversation_context', 'pending_approvals', 'resume_applications',
            'ai_filtering_results', 'job_statistics', 'email_templates', 'system_logs'
        ]
        
        cursor.execute("SHOW TABLES")
        existing_tables = [table[0] for table in cursor.fetchall()]
        
        logger.info("📋 Database Tables Status:")
        logger.info("=" * 50)
        
        all_tables_exist = True
        for table in expected_tables:
            if table in existing_tables:
                logger.info(f"✅ {table}")
            else:
                logger.info(f"❌ {table} - MISSING")
                all_tables_exist = False
        
        logger.info("=" * 50)
        
        if all_tables_exist:
            logger.info("🎉 All required tables are present!")
        else:
            logger.error("⚠️  Some tables are missing!")
        
        cursor.close()
        conn.close()
        return all_tables_exist
        
    except Error as e:
        logger.error(f"❌ Error verifying tables: {e}")
        if conn:
            conn.close()
        return False

def main():
    """Main function to setup the database"""
    print("🚀 Candidate Portal Database Setup")
    print("=" * 50)
    
    # Test database connection
    logger.info("Testing database connection...")
    conn = get_db_connection()
    if not conn:
        logger.error("❌ Failed to connect to database. Please check your MySQL configuration.")
        return False
    
    conn.close()
    logger.info("✅ Database connection successful!")
    
    # Create tables
    if not create_database_tables():
        logger.error("❌ Failed to create database tables")
        return False
    
    # Insert sample data
    if not insert_sample_data():
        logger.error("❌ Failed to insert sample data")
        return False
    
    # Verify tables
    if not verify_tables():
        logger.error("❌ Table verification failed")
        return False
    
    print("\n🎉 Database setup completed successfully!")
    print("=" * 50)
    print("📋 Next steps:")
    print("1. Start the backend server: python server.py")
    print("2. Start the HR portal: cd Frontend/hrmshiring-main && npm start")
    print("3. Start the candidate portal: cd Frontend/candidate-portal && npm start")
    print("=" * 50)
    
    return True

if __name__ == "__main__":
    success = main()
    sys.exit(0 if success else 1)
