#!/bin/bash

echo "🚀 Candidate Portal Setup Script"
echo "=================================="

# Check if Python is installed
if ! command -v python3 &> /dev/null; then
    echo "❌ Python 3 is not installed. Please install Python 3.8 or higher."
    exit 1
fi

echo "✅ Python 3 found: $(python3 --version)"

# Check if pip is installed
if ! command -v pip3 &> /dev/null; then
    echo "❌ pip3 is not installed. Please install pip3."
    exit 1
fi

echo "✅ pip3 found: $(pip3 --version)"

# Install Python dependencies
echo ""
echo "📦 Installing Python dependencies..."
pip3 install -r requirements.txt

if [ $? -ne 0 ]; then
    echo "❌ Failed to install Python dependencies"
    exit 1
fi

echo "✅ Python dependencies installed successfully!"

# Run database setup
echo ""
echo "🗄️  Setting up database..."
python3 setup_database.py

if [ $? -ne 0 ]; then
    echo "❌ Database setup failed"
    exit 1
fi

echo ""
echo "🎉 Setup completed successfully!"
echo "=================================="
echo "📋 Next steps:"
echo "1. Start the backend server: python3 server.py"
echo "2. Start the HR portal: cd ../Frontend/hrmshiring-main && npm start"
echo "3. Start the candidate portal: cd ../Frontend/candidate-portal && npm start"
echo "=================================="
