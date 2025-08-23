#!/usr/bin/env python3
"""
ai_filter_wrapper.py - Wrapper to run the AI filtering system
This script can be called by the server to run filtering for a specific ticket
"""

import sys
import os
import json
from pathlib import Path

def main():
    if len(sys.argv) < 2:
        print("Usage: python ai_filter_wrapper.py <ticket_folder_path>")
        sys.exit(1)
    
    ticket_folder = sys.argv[1]
    
    try:
        # Add the directory containing the AI filtering module to Python path
        current_dir = os.path.dirname(os.path.abspath(__file__))
        sys.path.insert(0, current_dir)
        
        # Import the AI filtering system
        try:
            from resume_filter5 import UpdatedResumeFilteringSystem
        except ImportError:
            from resume_filter4 import UpdatedResumeFilteringSystem
        
        print(f"Running AI filtering for: {ticket_folder}")
        
        # Create and run the filtering system
        filter_system = UpdatedResumeFilteringSystem(ticket_folder)
        results = filter_system.filter_resumes()
        
        if "error" not in results:
            # Create API-friendly results
            api_results = {
                'status': 'completed',
                'ticket_id': results.get('ticket_id'),
                'total_resumes': results['summary']['total_resumes'],
                'top_candidates': []
            }
            
            # Format top candidates
            for i, candidate in enumerate(results.get('final_top_5', results.get('top_5_candidates', []))):
                api_results['top_candidates'].append({
                    'rank': i + 1,
                    'filename': candidate['filename'],
                    'score': candidate['final_score'],
                    'skill_score': candidate['skill_score'],
                    'experience_score': candidate['experience_score'],
                    'professional_development_score': candidate.get('professional_development_score', 0),
                    'matched_skills': candidate['matched_skills'],
                    'experience_years': candidate['detected_experience_years']
                })
            
            # Save API results
            output_dir = Path(ticket_folder) / "filtering_results"
            output_dir.mkdir(exist_ok=True)
            
            api_results_file = output_dir / 'api_results.json'
            with open(api_results_file, 'w') as f:
                json.dump(api_results, f, indent=2)
            
            print(f"AI filtering completed successfully")
            return 0
        else:
            print(f"Error: {results.get('error')}")
            return 1
            
    except Exception as e:
        print(f"Error running AI filtering: {str(e)}")
        import traceback
        traceback.print_exc()
        return 1

if __name__ == "__main__":
    sys.exit(main())