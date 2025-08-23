# 🚀 Complete Candidate Portal System

A comprehensive hiring management system with dual portals - HR Portal for job posting and management, and Candidate Portal for job applications.

## ✨ Features

### 🏢 HR Portal
- **Job Creation & Management**: Create and manage job postings
- **Resume Processing**: AI-powered resume filtering and scoring
- **Application Tracking**: Monitor candidate applications
- **Chat Bot Integration**: AI hiring assistant
- **User Management**: HR user authentication and role management

### 👥 Candidate Portal
- **Job Browsing**: View all approved job postings
- **Application Submission**: Easy job application process
- **Resume Upload**: Upload and submit resumes
- **Application Status**: Track application progress

### 🤖 AI Features
- **Resume Filtering**: Intelligent resume screening
- **Job Matching**: Skills-based candidate matching
- **Automated Processing**: Streamlined hiring workflow

## 🏗️ Architecture

```
candidate_portal/
├── Backend/                 # Python Flask API
│   ├── server.py           # Main server with all endpoints
│   ├── ai_bot3.py          # AI chatbot functionality
│   ├── resume_filter5.py   # Resume filtering system
│   ├── email_process.py    # Email processing
│   └── setup_database.py   # Database setup
├── Frontend/
│   ├── hrmshiring-main/    # HR Portal (React)
│   └── candidate-portal/   # Candidate Portal (React + TypeScript)
```

## 🚀 Quick Start

### Prerequisites
- Python 3.8+
- Node.js 16+
- MySQL Database
- Git

### Backend Setup

1. **Clone the repository**
   ```bash
   git clone <your-repo-url>
   cd candidate_portal
   ```

2. **Install Python dependencies**
   ```bash
   cd Backend
   pip install -r requirements.txt
   ```

3. **Setup database**
   ```bash
   python setup_database.py
   ```

4. **Start the server**
   ```bash
   python server.py
   ```

### Frontend Setup

1. **HR Portal**
   ```bash
   cd Frontend/hrmshiring-main
   npm install
   npm start
   ```

2. **Candidate Portal**
   ```bash
   cd Frontend/candidate-portal
   npm install
   npm start
   ```

## 🔧 Configuration

### Environment Variables

Create `.env` files in the respective directories:

**Backend/.env:**
```env
MYSQL_HOST=localhost
MYSQL_USER=your_username
MYSQL_PASSWORD=your_password
MYSQL_DATABASE=candidate_portal
JWT_SECRET_KEY=your-secret-key
```

**Frontend/hrmshiring-main/.env:**
```env
REACT_APP_API_BASE_URL=http://localhost:5000
REACT_APP_API_KEY=sk-hiring-bot-2024-secret-key-xyz789
```

**Frontend/candidate-portal/.env:**
```env
REACT_APP_API_BASE_URL=http://localhost:5000
REACT_APP_API_KEY=sk-hiring-bot-2024-secret-key-xyz789
```

## 📊 Database Schema

The system uses MySQL with the following main tables:
- `users` - User authentication and roles
- `tickets` - Job postings and applications
- `ticket_details` - Job details and requirements
- `applications` - Candidate applications
- `resumes` - Resume storage and metadata

## 🔐 Authentication

- **JWT-based authentication** for HR users
- **API key authentication** for public endpoints
- **Role-based access control** (HR vs Candidate)

## 🤖 AI Integration

- **Resume Filtering**: ML-based resume screening
- **Skills Matching**: Intelligent candidate-job matching
- **Chat Bot**: AI-powered hiring assistant

## 📱 API Endpoints

### Public Endpoints
- `GET /api/jobs/approved` - Get approved job listings
- `POST /api/applications/{jobId}/submit` - Submit job application

### HR Endpoints (Authentication Required)
- `POST /api/hr/jobs` - Create new job posting
- `GET /api/hr/jobs/approved` - Get HR's approved jobs
- `GET /api/hr/applications` - Get applications for HR's jobs

## 🛠️ Development

### Running in Development Mode
```bash
# Backend (Terminal 1)
cd Backend
python server.py

# HR Portal (Terminal 2)
cd Frontend/hrmshiring-main
npm start

# Candidate Portal (Terminal 3)
cd Frontend/candidate-portal
npm start
```

### Building for Production
```bash
# HR Portal
cd Frontend/hrmshiring-main
npm run build

# Candidate Portal
cd Frontend/candidate-portal
npm run build
```

## 📝 License

This project is licensed under the MIT License.

## 🤝 Contributing

1. Fork the repository
2. Create a feature branch
3. Make your changes
4. Submit a pull request

## 📞 Support

For support and questions, please open an issue in the GitHub repository.

---

**Built with ❤️ using React, TypeScript, Python Flask, and MySQL**
