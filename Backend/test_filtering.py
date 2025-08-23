#!/usr/bin/env python3
"""Test the resume filtering system directly"""

import os
import sys
from pathlib import Path

# Test the imports
print("Testing imports...")
try:
    from resume_filter5 import UpdatedResumeFilteringSystem
    print("✅ Successfully imported UpdatedResumeFilteringSystem from resume_filter5")
except ImportError as e:
    print(f"❌ Failed to import from resume_filter5: {e}")
    sys.exit(1)

# Test filtering on the web-dev folder
ticket_folder = "/mnt/c/Users/Admin/Desktop/Candidate_portal/candidate_portal/Backend/approved_tickets/96842d6ce2_web-dev"

if not os.path.exists(ticket_folder):
    print(f"❌ Ticket folder not found: {ticket_folder}")
    sys.exit(1)

print(f"\n✅ Found ticket folder: {ticket_folder}")

# List resume files
resume_files = [f for f in os.listdir(ticket_folder) 
                if f.endswith(('.pdf', '.doc', '.docx', '.txt', '.rtf'))]
print(f"\n📄 Found {len(resume_files)} resume files:")
for rf in resume_files:
    print(f"   - {rf}")

# Try to run the filtering
print("\n🚀 Running filtering system...")
try:
    filter_system = UpdatedResumeFilteringSystem(ticket_folder)
    print("✅ Created filter system instance")
    
    results = filter_system.filter_resumes()
    print("\n✅ Filtering completed successfully!")
    
    if "error" in results:
        print(f"❌ Error in results: {results['error']}")
    else:
        print(f"\n📊 Results summary:")
        print(f"   - Total resumes processed: {results.get('summary', {}).get('total_resumes', 0)}")
        print(f"   - Top candidates: {len(results.get('final_top_5', []))}")
        
        if results.get('final_top_5'):
            print("\n🏆 Top 5 Candidates:")
            for i, candidate in enumerate(results['final_top_5'], 1):
                print(f"   {i}. {candidate.get('name', 'Unknown')} - Score: {candidate.get('score', 0):.2%}")
        
except Exception as e:
    print(f"\n❌ Exception during filtering: {type(e).__name__}: {e}")
    import traceback
    traceback.print_exc()

# Check if results were saved
filtering_results_path = os.path.join(ticket_folder, "filtering_results")
if os.path.exists(filtering_results_path):
    print(f"\n✅ Filtering results directory created: {filtering_results_path}")
    result_files = list(Path(filtering_results_path).glob('*'))
    print(f"   Files created: {len(result_files)}")
    for rf in result_files:
        print(f"   - {rf.name}")
else:
    print(f"\n❌ No filtering results directory found")