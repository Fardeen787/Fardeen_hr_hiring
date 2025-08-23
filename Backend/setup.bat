@echo off
echo 🚀 Candidate Portal Setup Script
echo ==================================

REM Check if Python is installed
python --version >nul 2>&1
if errorlevel 1 (
    echo ❌ Python is not installed. Please install Python 3.8 or higher.
    pause
    exit /b 1
)

echo ✅ Python found: 
python --version

REM Check if pip is installed
pip --version >nul 2>&1
if errorlevel 1 (
    echo ❌ pip is not installed. Please install pip.
    pause
    exit /b 1
)

echo ✅ pip found:
pip --version

REM Install Python dependencies
echo.
echo 📦 Installing Python dependencies...
pip install -r requirements.txt

if errorlevel 1 (
    echo ❌ Failed to install Python dependencies
    pause
    exit /b 1
)

echo ✅ Python dependencies installed successfully!

REM Run database setup
echo.
echo 🗄️  Setting up database...
python setup_database.py

if errorlevel 1 (
    echo ❌ Database setup failed
    pause
    exit /b 1
)

echo.
echo 🎉 Setup completed successfully!
echo ==================================
echo 📋 Next steps:
echo 1. Start the backend server: python server.py
echo 2. Start the HR portal: cd ..\Frontend\hrmshiring-main ^&^& npm start
echo 3. Start the candidate portal: cd ..\Frontend\candidate-portal ^&^& npm start
echo ==================================
pause
