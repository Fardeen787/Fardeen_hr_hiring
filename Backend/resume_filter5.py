# Resume Filtering System Without LLM - Pure Algorithmic Scoring
# All LLM dependencies removed, using only rule-based scoring

import os
import json
import PyPDF2
from docx import Document
import numpy as np
from typing import List, Dict, Tuple, Optional, Any, Set
from sklearn.feature_extraction.text import TfidfVectorizer
from sklearn.metrics.pairwise import cosine_similarity
import spacy
from datetime import datetime
import pandas as pd
from pathlib import Path
import re
import hashlib
import time
from difflib import SequenceMatcher
from collections import defaultdict
# import phonenumbers  # Not used, removed to avoid import issues
from fuzzywuzzy import fuzz
import jellyfish

# No need for OpenAI or AutoGen imports anymore
# Configuration simplified - no API keys needed

class ResumeExtractor:
    """Extract text from various resume formats"""
    
    @staticmethod
    def extract_text_from_pdf(file_path: str) -> str:
        """Extract text from PDF file"""
        try:
            with open(file_path, 'rb') as file:
                pdf_reader = PyPDF2.PdfReader(file)
                text = ""
                for page in pdf_reader.pages:
                    text += page.extract_text() + "\n"
                return text
        except Exception as e:
            print(f"Error reading PDF {file_path}: {e}")
            return ""
    
    @staticmethod
    def extract_text_from_docx(file_path: str) -> str:
        """Extract text from DOCX file"""
        try:
            doc = Document(file_path)
            text = "\n".join([paragraph.text for paragraph in doc.paragraphs])
            return text
        except Exception as e:
            print(f"Error reading DOCX {file_path}: {e}")
            return ""
    
    @staticmethod
    def extract_text(file_path: Path) -> str:
        """Extract text from resume file"""
        file_path_str = str(file_path)
        
        if file_path.suffix.lower() == '.pdf':
            return ResumeExtractor.extract_text_from_pdf(file_path_str)
        elif file_path.suffix.lower() in ['.docx', '.doc']:
            return ResumeExtractor.extract_text_from_docx(file_path_str)
        elif file_path.suffix.lower() == '.txt':
            with open(file_path_str, 'r', encoding='utf-8') as f:
                return f.read()
        else:
            return ""


class DuplicateCandidateDetector:
    """Advanced duplicate candidate detection system"""
    
    def __init__(self):
        self.candidates_db = {}
        self.email_to_id = {}
        self.phone_to_id = {}
        self.name_variations = defaultdict(set)
        
    def extract_candidate_identifiers(self, resume_text: str, filename: str) -> Dict:
        """Extract all possible identifiers from resume"""
        identifiers = {
            'filename': filename,
            'emails': self._extract_emails(resume_text),
            'phones': self._extract_phones(resume_text),
            'names': self._extract_names(resume_text),
            'github': self._extract_github(resume_text),
            'linkedin': self._extract_linkedin(resume_text),
            'content_hash': self._generate_content_hash(resume_text),
            'education_hash': self._generate_education_hash(resume_text),
            'experience_hash': self._generate_experience_hash(resume_text)
        }
        return identifiers
    
    def _extract_emails(self, text: str) -> List[str]:
        """Extract and validate email addresses"""
        email_pattern = r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b'
        emails = re.findall(email_pattern, text)
        
        valid_emails = []
        for email in emails:
            email_lower = email.lower()
            if not any(invalid in email_lower for invalid in ['example.com', 'test.com', '@gmail.co']):
                valid_emails.append(email_lower)
                
        return list(set(valid_emails))
    
    def _extract_phones(self, text: str) -> List[str]:
        """Extract and normalize phone numbers"""
        phone_patterns = [
            r'\+?1?\s*\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})',
            r'\+?(\d{1,3})[\s.-]?(\d{3,4})[\s.-]?(\d{3,4})[\s.-]?(\d{3,4})',
            r'\b(\d{10})\b',
            r'\+91[\s.-]?(\d{10})',
        ]
        
        phones = []
        for pattern in phone_patterns:
            matches = re.findall(pattern, text)
            for match in matches:
                if isinstance(match, tuple):
                    phone = ''.join(match)
                else:
                    phone = match
                
                phone_digits = re.sub(r'\D', '', phone)
                
                if len(phone_digits) >= 10:
                    normalized = phone_digits[-10:]
                    phones.append(normalized)
        
        return list(set(phones))
    
    def _extract_names(self, text: str) -> List[str]:
        """Extract potential names from resume"""
        names = []
        
        lines = text.split('\n')
        for i, line in enumerate(lines[:10]):
            line = line.strip()
            
            if not line or any(keyword in line.lower() for keyword in 
                             ['resume', 'curriculum', 'cv', 'objective', 'summary']):
                continue
            
            words = line.split()
            if 2 <= len(words) <= 4:
                if all(word[0].isupper() for word in words if word):
                    names.append(line)
        
        name_pattern = r'(?:Name|NAME|name)\s*[:|-]?\s*([A-Z][a-z]+(?:\s+[A-Z][a-z]+)*)'
        name_matches = re.findall(name_pattern, text)
        names.extend(name_matches)
        
        return list(set(names))
    
    def _extract_github(self, text: str) -> Optional[str]:
        """Extract GitHub username"""
        github_patterns = [
            r'github\.com/([a-zA-Z0-9-]+)',
            r'github\s*:\s*([a-zA-Z0-9-]+)',
            r'@([a-zA-Z0-9-]+)\s*\(github\)',
        ]
        
        for pattern in github_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        return None
    
    def _extract_linkedin(self, text: str) -> Optional[str]:
        """Extract LinkedIn profile ID"""
        linkedin_patterns = [
            r'linkedin\.com/in/([a-zA-Z0-9-]+)',
            r'linkedin\s*:\s*([a-zA-Z0-9-]+)',
        ]
        
        for pattern in linkedin_patterns:
            match = re.search(pattern, text, re.IGNORECASE)
            if match:
                return match.group(1).lower()
        return None
    
    def _generate_content_hash(self, text: str) -> str:
        """Generate hash of key content"""
        lines = text.split('\n')
        content_lines = lines[5:] if len(lines) > 5 else lines
        
        content = '\n'.join(content_lines)
        content = re.sub(r'\b[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Z|a-z]{2,}\b', '', content)
        content = re.sub(r'\+?1?\s*\(?(\d{3})\)?[\s.-]?(\d{3})[\s.-]?(\d{4})', '', content)
        
        content = ' '.join(content.split())
        
        return hashlib.md5(content.encode()).hexdigest()
    
    def _generate_education_hash(self, text: str) -> str:
        """Generate hash based on education details"""
        education_section = self._extract_section(text, ['education', 'academic', 'qualification'])
        
        degree_patterns = [
            r'(B\.?S\.?|B\.?Sc\.?|Bachelor|B\.?Tech|B\.?E\.?)',
            r'(M\.?S\.?|M\.?Sc\.?|Master|M\.?Tech|MBA|M\.?E\.?)',
            r'(Ph\.?D\.?|Doctorate)',
        ]
        
        degrees = []
        for pattern in degree_patterns:
            matches = re.findall(pattern, education_section, re.IGNORECASE)
            degrees.extend(matches)
        
        years = re.findall(r'\b(19\d{2}|20\d{2})\b', education_section)
        
        edu_string = ' '.join(sorted(degrees + years))
        return hashlib.md5(edu_string.encode()).hexdigest()[:16]
    
    def _generate_experience_hash(self, text: str) -> str:
        """Generate hash based on work experience"""
        experience_section = self._extract_section(text, ['experience', 'employment', 'work history'])
        
        companies = re.findall(r'\b([A-Z][a-zA-Z]+(?:\s+[A-Z][a-zA-Z]+)*)\b', experience_section)
        years = re.findall(r'\b(19\d{2}|20\d{2})\b', experience_section)
        
        tech_keywords = ['python', 'java', 'javascript', 'sql', 'aws', 'docker', 'kubernetes']
        techs_found = [tech for tech in tech_keywords if tech in experience_section.lower()]
        
        exp_string = ' '.join(sorted(companies[:5] + years + techs_found))
        return hashlib.md5(exp_string.encode()).hexdigest()[:16]
    
    def _extract_section(self, text: str, section_keywords: List[str]) -> str:
        """Extract a section from resume based on keywords"""
        lines = text.split('\n')
        section_start = -1
        section_lines = []
        
        for i, line in enumerate(lines):
            line_lower = line.lower()
            
            if any(keyword in line_lower for keyword in section_keywords):
                section_start = i
                continue
            
            if section_start >= 0:
                if any(keyword in line_lower for keyword in 
                      ['experience', 'education', 'skills', 'projects', 'summary', 'objective']):
                    if not any(keyword in line_lower for keyword in section_keywords):
                        break
                
                section_lines.append(line)
        
        return '\n'.join(section_lines)
    
    def calculate_similarity_score(self, id1: Dict, id2: Dict) -> Dict[str, float]:
        """Calculate similarity scores between two candidates"""
        scores = {
            'email_match': 0.0,
            'phone_match': 0.0,
            'name_similarity': 0.0,
            'github_match': 0.0,
            'linkedin_match': 0.0,
            'content_similarity': 0.0,
            'education_match': 0.0,
            'experience_match': 0.0
        }
        
        if id1['emails'] and id2['emails']:
            if set(id1['emails']) & set(id2['emails']):
                scores['email_match'] = 1.0
        
        if id1['phones'] and id2['phones']:
            if set(id1['phones']) & set(id2['phones']):
                scores['phone_match'] = 1.0
        
        if id1['names'] and id2['names']:
            max_similarity = 0.0
            for name1 in id1['names']:
                for name2 in id2['names']:
                    fuzzy_score = fuzz.token_sort_ratio(name1.lower(), name2.lower()) / 100.0
                    
                    try:
                        phonetic_score = 1.0 if jellyfish.soundex(name1) == jellyfish.soundex(name2) else 0.0
                    except:
                        phonetic_score = 0.0
                    
                    contains_score = 0.8 if (name1.lower() in name2.lower() or 
                                           name2.lower() in name1.lower()) else 0.0
                    
                    similarity = max(fuzzy_score, phonetic_score, contains_score)
                    max_similarity = max(max_similarity, similarity)
            
            scores['name_similarity'] = max_similarity
        
        if id1['github'] and id2['github']:
            scores['github_match'] = 1.0 if id1['github'] == id2['github'] else 0.0
        
        if id1['linkedin'] and id2['linkedin']:
            scores['linkedin_match'] = 1.0 if id1['linkedin'] == id2['linkedin'] else 0.0
        
        if id1['content_hash'] == id2['content_hash']:
            scores['content_similarity'] = 1.0
        
        if id1['education_hash'] == id2['education_hash']:
            scores['education_match'] = 0.8
        
        if id1['experience_hash'] == id2['experience_hash']:
            scores['experience_match'] = 0.8
        
        return scores
    
    def is_duplicate(self, scores: Dict[str, float]) -> Tuple[bool, float, str]:
        """Determine if two candidates are duplicates based on scores"""
        
        if scores['email_match'] == 1.0:
            return True, 1.0, "Same email address"
        
        if scores['phone_match'] == 1.0:
            return True, 0.95, "Same phone number"
        
        if scores['github_match'] == 1.0:
            return True, 0.95, "Same GitHub account"
        
        if scores['linkedin_match'] == 1.0:
            return True, 0.95, "Same LinkedIn profile"
        
        if scores['content_similarity'] == 1.0:
            return True, 0.9, "Identical resume content"
        
        weighted_score = (
            scores['name_similarity'] * 0.2 +
            scores['education_match'] * 0.3 +
            scores['experience_match'] * 0.3 +
            scores['content_similarity'] * 0.2
        )
        
        if (scores['name_similarity'] > 0.7 and 
            scores['education_match'] > 0.7 and 
            scores['experience_match'] > 0.7):
            return True, weighted_score, "High similarity in name, education, and experience"
        
        if weighted_score > 0.85:
            return True, weighted_score, "Very high overall similarity"
        
        return False, weighted_score, "Not duplicate"
    
    def add_candidate(self, resume_text: str, filename: str) -> Tuple[str, List[Dict]]:
        """Add candidate and check for duplicates"""
        identifiers = self.extract_candidate_identifiers(resume_text, filename)
        
        duplicates = []
        
        for email in identifiers['emails']:
            if email in self.email_to_id:
                existing_id = self.email_to_id[email]
                existing = self.candidates_db[existing_id]
                scores = self.calculate_similarity_score(identifiers, existing)
                is_dup, confidence, reason = self.is_duplicate(scores)
                if is_dup:
                    duplicates.append({
                        'candidate_id': existing_id,
                        'filename': existing['filename'],
                        'confidence': confidence,
                        'reason': reason,
                        'matched_by': 'email'
                    })
        
        for phone in identifiers['phones']:
            if phone in self.phone_to_id:
                existing_id = self.phone_to_id[phone]
                if not any(d['candidate_id'] == existing_id for d in duplicates):
                    existing = self.candidates_db[existing_id]
                    scores = self.calculate_similarity_score(identifiers, existing)
                    is_dup, confidence, reason = self.is_duplicate(scores)
                    if is_dup:
                        duplicates.append({
                            'candidate_id': existing_id,
                            'filename': existing['filename'],
                            'confidence': confidence,
                            'reason': reason,
                            'matched_by': 'phone'
                        })
        
        if not duplicates:
            for cand_id, candidate in self.candidates_db.items():
                scores = self.calculate_similarity_score(identifiers, candidate)
                is_dup, confidence, reason = self.is_duplicate(scores)
                if is_dup:
                    duplicates.append({
                        'candidate_id': cand_id,
                        'filename': candidate['filename'],
                        'confidence': confidence,
                        'reason': reason,
                        'matched_by': 'similarity'
                    })
        
        candidate_id = hashlib.md5(f"{filename}_{datetime.now().isoformat()}".encode()).hexdigest()[:12]
        
        self.candidates_db[candidate_id] = identifiers
        
        for email in identifiers['emails']:
            self.email_to_id[email] = candidate_id
        
        for phone in identifiers['phones']:
            self.phone_to_id[phone] = candidate_id
        
        for name in identifiers['names']:
            self.name_variations[name.lower()].add(candidate_id)
        
        return candidate_id, duplicates
    
    def get_duplicate_groups(self) -> List[List[Dict]]:
        """Get groups of duplicate candidates with details"""
        groups = []
        processed = set()
        
        for cand_id in self.candidates_db:
            if cand_id in processed:
                continue
            
            group = [{'candidate_id': cand_id, 'filename': self.candidates_db[cand_id]['filename']}]
            processed.add(cand_id)
            
            candidate = self.candidates_db[cand_id]
            
            for email in candidate['emails']:
                for other_id in self.candidates_db:
                    if other_id != cand_id and other_id not in processed:
                        if email in self.candidates_db[other_id]['emails']:
                            group.append({
                                'candidate_id': other_id,
                                'filename': self.candidates_db[other_id]['filename']
                            })
                            processed.add(other_id)
            
            for phone in candidate['phones']:
                for other_id in self.candidates_db:
                    if other_id != cand_id and other_id not in processed:
                        if phone in self.candidates_db[other_id]['phones']:
                            group.append({
                                'candidate_id': other_id,
                                'filename': self.candidates_db[other_id]['filename']
                            })
                            processed.add(other_id)
            
            if len(group) > 1:
                groups.append(group)
        
        return groups


class DuplicateHandlingStrategy:
    """Strategies for handling duplicate candidates"""
    
    @staticmethod
    def merge_scores(candidates: List[Dict]) -> Dict:
        """Merge scores from duplicate candidates, taking the best scores"""
        if not candidates:
            return {}
        
        merged = candidates[0].copy()
        
        all_filenames = [c['filename'] for c in candidates]
        merged['all_filenames'] = all_filenames
        merged['duplicate_count'] = len(candidates)
        
        for candidate in candidates[1:]:
            if candidate.get('final_score', 0) > merged.get('final_score', 0):
                merged['final_score'] = candidate['final_score']
            
            if candidate.get('skill_score', 0) > merged.get('skill_score', 0):
                merged['skill_score'] = candidate['skill_score']
                merged['matched_skills'] = candidate.get('matched_skills', [])
            
            if candidate.get('experience_score', 0) > merged.get('experience_score', 0):
                merged['experience_score'] = candidate['experience_score']
                merged['detected_experience_years'] = candidate.get('detected_experience_years', 0)
            
            if candidate.get('professional_development_score', 0) > merged.get('professional_development_score', 0):
                merged['professional_development_score'] = candidate['professional_development_score']
                merged['professional_development'] = candidate.get('professional_development', {})
        
        merged['has_duplicates'] = True
        merged['duplicate_info'] = {
            'count': len(candidates),
            'filenames': all_filenames,
            'selected_filename': merged['filename']
        }
        
        return merged


class EnhancedJobTicket:
    """Enhanced JobTicket class that reads latest updates from JSON structure"""
    
    def __init__(self, ticket_folder: str):
        self.ticket_folder = Path(ticket_folder)
        self.ticket_id = self.ticket_folder.name
        self.raw_data = self._load_raw_data()
        self.job_details = self._merge_with_updates()
        self._print_loaded_details()
    
    def _load_raw_data(self) -> Dict:
        """Load the raw JSON data from the ticket folder"""
        priority_files = ['job_details.json', 'job-data.json', 'job.json']
        json_file = None
        
        for filename in priority_files:
            file_path = self.ticket_folder / filename
            if file_path.exists():
                json_file = file_path
                break
        
        if not json_file:
            json_files = [f for f in self.ticket_folder.glob("*.json") 
                         if f.name not in ['metadata.json', 'applications.json']]
            if json_files:
                json_file = json_files[0]
        
        if not json_file:
            app_file = self.ticket_folder / 'applications.json'
            if app_file.exists():
                json_file = app_file
            else:
                raise FileNotFoundError(f"No JSON file found in {self.ticket_folder}")
        
        print(f"📄 Loading job details from: {json_file.name}")
        
        job_desc_file = self.ticket_folder / 'job-description.txt'
        job_description_text = ""
        if job_desc_file.exists():
            print(f"📝 Loading job description from: job-description.txt")
            with open(job_desc_file, 'r', encoding='utf-8') as f:
                job_description_text = f.read()
        
        try:
            with open(json_file, 'r', encoding='utf-8') as f:
                data = json.load(f)
            
            if job_description_text and isinstance(data, dict):
                if 'job_description' not in data:
                    data['job_description'] = job_description_text
                if 'job_details' in data and 'job_description' not in data['job_details']:
                    data['job_details']['job_description'] = job_description_text
            
            return data
        except Exception as e:
            print(f"❌ Error loading JSON: {e}")
            raise
    
    def _merge_with_updates(self) -> Dict:
        """Merge initial details with latest updates"""
        if isinstance(self.raw_data, list):
            print("📝 Detected applications list format, creating job structure...")
            merged_details = {
                'ticket_id': self.ticket_id,
                'applications': self.raw_data,
                'status': 'active',
                'created_at': datetime.now().isoformat(),
                'last_updated': datetime.now().isoformat(),
                'job_title': 'Software Developer',
                'position': 'Software Developer',
                'experience_required': '2+ years',
                'location': 'Remote',
                'salary_range': 'Competitive',
                'required_skills': 'Python, JavaScript, SQL',
                'job_description': 'We are looking for a talented developer',
                'deadline': 'Open until filled'
            }
            return merged_details
        
        if 'ticket_info' in self.raw_data and 'job_details' in self.raw_data:
            merged_details = self.raw_data['job_details'].copy()
            merged_details['ticket_id'] = self.raw_data['ticket_info'].get('ticket_id', self.ticket_id)
            merged_details['status'] = self.raw_data['ticket_info'].get('status', 'active')
            merged_details['created_at'] = self.raw_data['ticket_info'].get('created_at', '')
            merged_details['last_updated'] = self.raw_data.get('saved_at', '')
            return merged_details
        
        if 'initial_details' in self.raw_data:
            merged_details = self.raw_data['initial_details'].copy()
        else:
            merged_details = self.raw_data.copy()
        
        merged_details['ticket_id'] = self.raw_data.get('ticket_id', self.ticket_id)
        merged_details['status'] = self.raw_data.get('status', 'unknown')
        merged_details['created_at'] = self.raw_data.get('created_at', '')
        merged_details['last_updated'] = self.raw_data.get('last_updated', '')
        
        if 'updates' in self.raw_data and self.raw_data['updates']:
            print(f"📝 Found {len(self.raw_data['updates'])} update(s)")
            
            sorted_updates = sorted(
                self.raw_data['updates'], 
                key=lambda x: x.get('timestamp', ''),
                reverse=True
            )
            
            latest_update = sorted_updates[0]
            print(f"✅ Applying latest update from: {latest_update.get('timestamp', 'unknown')}")
            
            if 'details' in latest_update:
                for key, value in latest_update['details'].items():
                    if value:
                        merged_details[key] = value
                        print(f"   Updated {key}: {value}")
        
        return merged_details
    
    def _print_loaded_details(self):
        """Print the loaded job details for verification"""
        print("\n" + "="*60)
        print("📋 LOADED JOB REQUIREMENTS")
        print("="*60)
        print(f"Position: {self.position}")
        print(f"Experience: {self.experience_required}")
        print(f"Location: {self.location}")
        print(f"Salary: {self.salary_range}")
        print(f"Skills: {', '.join(self.tech_stack)}")
        print(f"Deadline: {self.deadline}")
        print(f"Last Updated: {self.job_details.get('last_updated', 'Unknown')}")
        print("="*60 + "\n")
    
    def _parse_skills(self, skills_str: str) -> List[str]:
        """Parse skills from string format to list"""
        if isinstance(skills_str, list):
            return skills_str
        
        if not skills_str:
            return []
        
        skills = re.split(r'[,;|]\s*', skills_str)
        expanded_skills = []
        
        for skill in skills:
            if '(' in skill and ')' in skill:
                main_skill = skill[:skill.index('(')].strip()
                variations = skill[skill.index('(')+1:skill.index(')')].strip()
                expanded_skills.append(main_skill)
                if '/' in variations:
                    expanded_skills.extend([v.strip() for v in variations.split('/')])
                else:
                    expanded_skills.append(variations)
            else:
                expanded_skills.append(skill.strip())
        
        return list(set([s for s in expanded_skills if s]))
    
    @property
    def position(self) -> str:
        return (self.job_details.get('job_title') or 
                self.job_details.get('position') or 
                self.job_details.get('title', 'Unknown Position'))
    
    @property
    def experience_required(self) -> str:
        return (self.job_details.get('experience_required') or 
                self.job_details.get('experience') or 
                self.job_details.get('years_of_experience', '0+ years'))
    
    @property
    def location(self) -> str:
        return self.job_details.get('location', 'Not specified')
    
    @property
    def salary_range(self) -> str:
        salary = self.job_details.get('salary_range', '')
        if isinstance(salary, dict):
            min_sal = salary.get('min', '')
            max_sal = salary.get('max', '')
            currency = salary.get('currency', 'INR')
            return f"{currency} {min_sal}-{max_sal}"
        return salary or 'Not specified'
    
    @property
    def deadline(self) -> str:
        return self.job_details.get('deadline', 'Not specified')
    
    @property
    def tech_stack(self) -> List[str]:
        skills = self.job_details.get('required_skills') or self.job_details.get('tech_stack', '')
        return self._parse_skills(skills)
    
    @property
    def requirements(self) -> List[str]:
        requirements = []
        
        if self.job_details.get('job_description'):
            requirements.append(self.job_details['job_description'])
        
        req_field = self.job_details.get('requirements', [])
        if isinstance(req_field, str):
            requirements.extend([r.strip() for r in req_field.split('\n') if r.strip()])
        elif isinstance(req_field, list):
            requirements.extend(req_field)
        
        return requirements
    
    @property
    def description(self) -> str:
        return (self.job_details.get('job_description') or 
                self.job_details.get('description') or 
                self.job_details.get('summary', ''))
    
    @property
    def employment_type(self) -> str:
        return self.job_details.get('employment_type', 'Full-time')
    
    @property
    def nice_to_have(self) -> List[str]:
        nice = (self.job_details.get('nice_to_have') or 
                self.job_details.get('preferred_skills') or 
                self.job_details.get('bonus_skills', []))
        
        if isinstance(nice, str):
            return [n.strip() for n in nice.split('\n') if n.strip()]
        elif isinstance(nice, list):
            return nice
        return []
    
    def get_resumes(self) -> List[Path]:
        """Get all resume files from the ticket folder"""
        resume_extensions = ['.pdf', '.docx', '.doc']
        resumes = []
        
        for ext in resume_extensions:
            resumes.extend(self.ticket_folder.glob(f"*{ext}"))
        
        excluded_keywords = ['job_description', 'job-description', 'requirements', 'jd', 'job_posting', 'job-posting']
        filtered_resumes = []
        
        for resume in resumes:
            if not any(keyword in resume.name.lower().replace('_', '-') for keyword in excluded_keywords):
                filtered_resumes.append(resume)
            else:
                print(f"   ℹ️ Excluding non-resume file: {resume.name}")
        
        return filtered_resumes


class ProfessionalDevelopmentScorer:
    """Score candidates based on continuous learning and professional development"""
    
    def __init__(self):
        self.current_year = datetime.now().year
        self.current_month = datetime.now().month
        
        self.certifications_db = {
            'cloud': {
                'aws': {
                    'patterns': [
                        'aws certified solutions architect', 'aws certified developer',
                        'aws certified sysops', 'aws certified devops', 'aws certified security',
                        'aws certified database', 'aws certified machine learning',
                        'aws certified data analytics', 'aws solutions architect',
                        'amazon web services certified', 'aws certification'
                    ],
                    'weight': 1.0,
                    'recency_important': True
                },
                'azure': {
                    'patterns': [
                        'azure certified', 'azure fundamentals', 'azure administrator',
                        'azure developer', 'azure solutions architect', 'azure devops',
                        'azure data engineer', 'azure ai engineer', 'microsoft certified azure',
                        'az-900', 'az-104', 'az-204', 'az-303', 'az-304', 'az-400'
                    ],
                    'weight': 1.0,
                    'recency_important': True
                },
                'gcp': {
                    'patterns': [
                        'google cloud certified', 'gcp certified', 'google cloud professional',
                        'cloud architect google', 'cloud engineer google', 'data engineer google',
                        'google cloud developer', 'google cloud network engineer'
                    ],
                    'weight': 1.0,
                    'recency_important': True
                }
            },
            'data': {
                'general': {
                    'patterns': [
                        'databricks certified', 'cloudera certified', 'hortonworks certified',
                        'mongodb certified', 'cassandra certified', 'elastic certified',
                        'confluent certified', 'snowflake certified', 'tableau certified',
                        'power bi certified', 'qlik certified'
                    ],
                    'weight': 0.9,
                    'recency_important': True
                }
            },
            'programming': {
                'general': {
                    'patterns': [
                        'oracle certified java', 'microsoft certified c#', 'python institute certified',
                        'javascript certified', 'golang certified', 'rust certified',
                        'scala certified', 'kotlin certified'
                    ],
                    'weight': 0.8,
                    'recency_important': True
                }
            },
            'devops': {
                'general': {
                    'patterns': [
                        'docker certified', 'kubernetes certified', 'cka', 'ckad', 'cks',
                        'jenkins certified', 'ansible certified', 'terraform certified',
                        'gitlab certified', 'github actions certified'
                    ],
                    'weight': 0.9,
                    'recency_important': True
                }
            },
            'security': {
                'general': {
                    'patterns': [
                        'cissp', 'ceh', 'certified ethical hacker', 'comptia security+',
                        'comptia pentest+', 'gsec', 'gcih', 'oscp', 'security certified'
                    ],
                    'weight': 0.85,
                    'recency_important': True
                }
            },
            'agile': {
                'general': {
                    'patterns': [
                        'certified scrum master', 'csm', 'psm', 'safe certified',
                        'pmp', 'prince2', 'agile certified', 'kanban certified',
                        'product owner certified', 'cspo'
                    ],
                    'weight': 0.7,
                    'recency_important': False
                }
            },
            'ai_ml': {
                'general': {
                    'patterns': [
                        'tensorflow certified', 'pytorch certified', 'deep learning certified',
                        'machine learning certified', 'ai certified', 'coursera deep learning',
                        'fast.ai certified', 'nvidia certified'
                    ],
                    'weight': 0.95,
                    'recency_important': True
                }
            }
        }
        
        self.learning_platforms = {
            'premium': {
                'patterns': ['coursera', 'udacity', 'edx', 'pluralsight', 'linkedin learning', 
                           'datacamp', 'udemy business', 'o\'reilly', 'safari books'],
                'weight': 0.8
            },
            'standard': {
                'patterns': ['udemy', 'skillshare', 'khan academy', 'codecademy', 
                           'freecodecamp', 'w3schools'],
                'weight': 0.6
            },
            'specialized': {
                'patterns': ['fast.ai', 'deeplearning.ai', 'kaggle learn', 'qwiklabs',
                           'linux academy', 'cloud academy', 'acloud.guru'],
                'weight': 0.9
            }
        }
        
        self.conference_patterns = {
            'speaking': {
                'patterns': [
                    'speaker at', 'presented at', 'talk at', 'keynote', 'panelist',
                    'conference speaker', 'tech talk', 'lightning talk', 'workshop facilitator'
                ],
                'weight': 1.0
            },
            'attendance': {
                'patterns': [
                    'attended', 'participant', 'conference attendee', 'summit participant',
                    'bootcamp', 'workshop attended', 'training attended'
                ],
                'weight': 0.5
            },
            'major_conferences': {
                'patterns': [
                    're:invent', 'google i/o', 'microsoft build', 'kubecon', 'pycon',
                    'jsconf', 'defcon', 'black hat', 'rsa conference', 'strata',
                    'spark summit', 'kafka summit', 'dockercon', 'hashiconf'
                ],
                'weight': 0.8
            }
        }
        
        self.content_creation = {
            'blog': {
                'patterns': [
                    'blog', 'medium.com', 'dev.to', 'hashnode', 'technical blog',
                    'tech blogger', 'write about', 'published articles', 'technical writing'
                ],
                'weight': 0.8
            },
            'video': {
                'patterns': [
                    'youtube channel', 'video tutorials', 'screencast', 'tech videos',
                    'online instructor', 'course creator'
                ],
                'weight': 0.9
            },
            'open_source': {
                'patterns': [
                    'github.com', 'gitlab.com', 'bitbucket', 'open source contributor',
                    'maintainer', 'pull requests', 'github stars', 'npm package',
                    'pypi package', 'maven package'
                ],
                'weight': 1.0
            },
            'community': {
                'patterns': [
                    'stack overflow', 'stackoverflow reputation', 'forum moderator',
                    'discord community', 'slack community', 'reddit moderator',
                    'community leader', 'meetup organizer'
                ],
                'weight': 0.7
            }
        }
    
    def extract_years_from_text(self, text: str, keyword: str, look_ahead: int = 50) -> List[int]:
        """Extract years mentioned near a keyword"""
        years_found = []
        keyword_indices = [m.start() for m in re.finditer(keyword, text.lower())]
        
        for idx in keyword_indices:
            start = max(0, idx - 30)
            end = min(len(text), idx + len(keyword) + look_ahead)
            snippet = text[start:end]
            
            year_pattern = r'\b(20[1-2][0-9])\b'
            years = re.findall(year_pattern, snippet)
            years_found.extend([int(y) for y in years if 2010 <= int(y) <= self.current_year + 1])
        
        return years_found
    
    def calculate_recency_score(self, years: List[int]) -> float:
        """Calculate how recent the certifications/courses are"""
        if not years:
            return 0.5
        
        most_recent = max(years)
        years_ago = self.current_year - most_recent
        
        if years_ago == 0:
            return 1.0
        elif years_ago == 1:
            return 0.9
        elif years_ago == 2:
            return 0.8
        elif years_ago == 3:
            return 0.6
        elif years_ago <= 5:
            return 0.4
        else:
            return 0.2
    
    def score_certifications(self, resume_text: str) -> Dict[str, Any]:
        """Score professional certifications"""
        resume_lower = resume_text.lower()
        
        results = {
            'certification_score': 0.0,
            'certification_count': 0,
            'recent_certification_score': 0.0,
            'certifications_found': [],
            'certification_categories': {},
            'years_detected': []
        }
        
        found_certs = set()
        category_scores = {}
        all_years = []
        
        for category, cert_types in self.certifications_db.items():
            category_scores[category] = 0.0
            category_certs = []
            
            for cert_type, cert_info in cert_types.items():
                for pattern in cert_info['patterns']:
                    if pattern in resume_lower and pattern not in found_certs:
                        found_certs.add(pattern)
                        results['certification_count'] += 1
                        category_certs.append(pattern)
                        
                        years = self.extract_years_from_text(resume_text, pattern)
                        all_years.extend(years)
                        
                        category_scores[category] += cert_info['weight']
            
            if category_certs:
                results['certification_categories'][category] = category_certs
        
        if results['certification_count'] > 0:
            base_score = min(results['certification_count'] * 0.15, 0.6)
            
            category_diversity = len(results['certification_categories']) / len(self.certifications_db)
            diversity_bonus = category_diversity * 0.2
            
            high_value_bonus = 0.0
            if any(cat in results['certification_categories'] for cat in ['cloud', 'ai_ml', 'data']):
                high_value_bonus = 0.2
            
            results['certification_score'] = min(base_score + diversity_bonus + high_value_bonus, 1.0)
        
        if all_years:
            results['years_detected'] = sorted(list(set(all_years)), reverse=True)
            results['recent_certification_score'] = self.calculate_recency_score(all_years)
        
        results['certifications_found'] = list(found_certs)
        
        return results
    
    def score_online_learning(self, resume_text: str) -> Dict[str, Any]:
        """Score online course completions"""
        resume_lower = resume_text.lower()
        
        results = {
            'online_learning_score': 0.0,
            'platforms_found': [],
            'course_count_estimate': 0,
            'recent_learning_score': 0.0,
            'specializations_mentioned': False
        }
        
        platforms_detected = set()
        platform_weights = []
        
        for tier, platform_info in self.learning_platforms.items():
            for platform in platform_info['patterns']:
                if platform in resume_lower:
                    platforms_detected.add(platform)
                    platform_weights.append(platform_info['weight'])
        
        results['platforms_found'] = list(platforms_detected)
        
        course_indicators = [
            r'completed?\s+\d+\s+courses?',
            r'\d+\s+courses?\s+completed',
            r'certification?\s+in',
            r'specialization\s+in',
            r'nanodegree',
            r'micromasters',
            r'professional certificate'
        ]
        
        course_count = 0
        for pattern in course_indicators:
            matches = re.findall(pattern, resume_lower)
            course_count += len(matches)
        
        if any(term in resume_lower for term in ['specialization', 'nanodegree', 'micromasters']):
            results['specializations_mentioned'] = True
            course_count += 2
        
        results['course_count_estimate'] = course_count
        
        if platforms_detected:
            platform_score = sum(platform_weights) / len(platform_weights) if platform_weights else 0
            course_bonus = min(course_count * 0.1, 0.3)
            spec_bonus = 0.2 if results['specializations_mentioned'] else 0
            
            results['online_learning_score'] = min(platform_score * 0.5 + course_bonus + spec_bonus, 1.0)
        
        recent_years = []
        for platform in platforms_detected:
            years = self.extract_years_from_text(resume_text, platform)
            recent_years.extend(years)
        
        if recent_years:
            results['recent_learning_score'] = self.calculate_recency_score(recent_years)
        
        return results
    
    def score_conference_participation(self, resume_text: str) -> Dict[str, Any]:
        """Score conference attendance and speaking"""
        resume_lower = resume_text.lower()
        
        results = {
            'conference_score': 0.0,
            'speaking_score': 0.0,
            'attendance_score': 0.0,
            'events_found': [],
            'speaker_events': [],
            'major_conferences': []
        }
        
        for pattern in self.conference_patterns['speaking']['patterns']:
            if pattern in resume_lower:
                results['speaker_events'].append(pattern)
                event_matches = re.findall(f'{pattern}[^.]*(?:conference|summit|meetup|workshop)', resume_lower)
                results['events_found'].extend(event_matches)
        
        for pattern in self.conference_patterns['attendance']['patterns']:
            if pattern in resume_lower:
                results['events_found'].append(pattern)
        
        for conference in self.conference_patterns['major_conferences']['patterns']:
            if conference in resume_lower:
                results['major_conferences'].append(conference)
        
        if results['speaker_events']:
            results['speaking_score'] = min(len(results['speaker_events']) * 0.3, 1.0)
        
        if results['events_found'] or results['major_conferences']:
            attendance_count = len(results['events_found']) + len(results['major_conferences'])
            results['attendance_score'] = min(attendance_count * 0.15, 0.6)
        
        results['conference_score'] = min(
            results['speaking_score'] * 0.7 + results['attendance_score'] * 0.3,
            1.0
        )
        
        return results
    
    def score_content_creation(self, resume_text: str) -> Dict[str, Any]:
        """Score technical content creation and community involvement"""
        resume_lower = resume_text.lower()
        
        results = {
            'content_creation_score': 0.0,
            'blog_writing': False,
            'video_content': False,
            'open_source': False,
            'community_involvement': False,
            'content_platforms': [],
            'github_activity': None
        }
        
        content_scores = []
        
        for content_type, content_info in self.content_creation.items():
            for pattern in content_info['patterns']:
                if pattern in resume_lower:
                    results[f'{content_type}_activity'] = True
                    results['content_platforms'].append(pattern)
                    content_scores.append(content_info['weight'])
                    
                    if 'github' in pattern:
                        stats_patterns = [
                            r'(\d+)\+?\s*stars',
                            r'(\d+)\+?\s*followers',
                            r'(\d+)\+?\s*repositories',
                            r'(\d+)\+?\s*contributions'
                        ]
                        github_stats = {}
                        for stat_pattern in stats_patterns:
                            match = re.search(stat_pattern, resume_lower)
                            if match:
                                github_stats[stat_pattern] = int(match.group(1))
                        if github_stats:
                            results['github_activity'] = github_stats
        
        if content_scores:
            base_score = sum(content_scores) / len(content_scores)
            variety_bonus = min(len(content_scores) * 0.1, 0.3)
            results['content_creation_score'] = min(base_score + variety_bonus, 1.0)
        
        return results
    
    def calculate_professional_development_score(self, resume_text: str) -> Dict[str, Any]:
        """Calculate comprehensive professional development score"""
        
        cert_results = self.score_certifications(resume_text)
        learning_results = self.score_online_learning(resume_text)
        conference_results = self.score_conference_participation(resume_text)
        content_results = self.score_content_creation(resume_text)
        
        weights = {
            'certifications': 0.35,
            'online_learning': 0.25,
            'conferences': 0.20,
            'content_creation': 0.20
        }
        
        weighted_score = (
            weights['certifications'] * cert_results['certification_score'] +
            weights['online_learning'] * learning_results['online_learning_score'] +
            weights['conferences'] * conference_results['conference_score'] +
            weights['content_creation'] * content_results['content_creation_score']
        )
        
        recency_scores = [
            cert_results.get('recent_certification_score', 0),
            learning_results.get('recent_learning_score', 0)
        ]
        recency_bonus = max(recency_scores) * 0.1 if recency_scores else 0
        
        final_score = min(weighted_score + recency_bonus, 1.0)
        
        pd_level = self._determine_pd_level(final_score, cert_results, learning_results, 
                                           conference_results, content_results)
        
        return {
            'professional_development_score': final_score,
            'professional_development_level': pd_level,
            'component_scores': {
                'certifications': cert_results,
                'online_learning': learning_results,
                'conferences': conference_results,
                'content_creation': content_results
            },
            'weights_used': weights,
            'summary': self._generate_pd_summary(cert_results, learning_results, 
                                                conference_results, content_results)
        }
    
    def _determine_pd_level(self, score: float, cert_results: Dict, learning_results: Dict,
                           conference_results: Dict, content_results: Dict) -> str:
        """Determine professional development level"""
        
        if score >= 0.8:
            return "Exceptional - Continuous learner with strong industry presence"
        elif score >= 0.6:
            return "Strong - Active in professional development"
        elif score >= 0.4:
            return "Moderate - Some professional development activities"
        elif score >= 0.2:
            return "Basic - Limited professional development shown"
        else:
            return "Minimal - Little evidence of continuous learning"
    
    def _generate_pd_summary(self, cert_results: Dict, learning_results: Dict,
                            conference_results: Dict, content_results: Dict) -> Dict[str, Any]:
        """Generate summary of professional development findings"""
        
        summary = {
            'total_certifications': cert_results['certification_count'],
            'certification_categories': list(cert_results['certification_categories'].keys()),
            'recent_certifications': cert_results['recent_certification_score'] > 0.7,
            'learning_platforms_used': len(learning_results['platforms_found']),
            'estimated_courses_completed': learning_results['course_count_estimate'],
            'conference_speaker': len(conference_results['speaker_events']) > 0,
            'conferences_attended': len(conference_results['events_found']),
            'content_creator': content_results['content_creation_score'] > 0.5,
            'content_types': [k.replace('_activity', '') for k, v in content_results.items() 
                            if k.endswith('_activity') and v],
            'continuous_learner': (
                cert_results['recent_certification_score'] > 0.7 or 
                learning_results['recent_learning_score'] > 0.7
            )
        }
        
        highlights = []
        if summary['total_certifications'] >= 3:
            highlights.append(f"Has {summary['total_certifications']} professional certifications")
        if summary['conference_speaker']:
            highlights.append("Conference speaker")
        if summary['content_creator']:
            highlights.append("Active content creator")
        if summary['continuous_learner']:
            highlights.append("Recent learning activities (within 2 years)")
        if 'cloud' in summary['certification_categories']:
            highlights.append("Cloud certified professional")
        
        summary['key_highlights'] = highlights
        
        return summary


class UpdateAwareResumeFilter:
    """Resume filter that considers updated job requirements and professional development"""
    
    def __init__(self):
        self.skill_variations = self._build_skill_variations()
        self.pd_scorer = ProfessionalDevelopmentScorer()
    
    def _build_skill_variations(self) -> Dict[str, List[str]]:
        """Build comprehensive skill variations dictionary"""
        return {
            "python": ["python", "py", "python3", "python2", "python 3", "python 2"],
            "javascript": ["javascript", "js", "node.js", "nodejs", "node", "ecmascript", "es6", "es5"],
            "java": ["java", "jvm", "j2ee", "java8", "java11", "java17"],
            "c++": ["c++", "cpp", "cplusplus", "c plus plus"],
            "c#": ["c#", "csharp", "c sharp", ".net", "dotnet"],
            "html": ["html", "html5", "html 5"],
            "css": ["css", "css3", "css 3", "styles", "styling"],
            "html/css": ["html/css", "html css", "html, css", "html and css", "html & css"],
            "sql": ["sql", "structured query language", "tsql", "t-sql", "plsql", "pl/sql"],
            "mongodb": ["mongodb", "mongo", "mongod", "nosql mongodb"],
            "redis": ["redis", "redis cache", "redis db", "redis database"],
            "postgresql": ["postgresql", "postgres", "pgsql", "postgre"],
            "mysql": ["mysql", "my sql", "mariadb"],
            "react": ["react", "reactjs", "react.js", "react js", "react native"],
            "angular": ["angular", "angularjs", "angular.js", "angular js"],
            "django": ["django", "django rest", "drf", "django framework"],
            "spring": ["spring", "spring boot", "springboot", "spring framework"],
            "flask": ["flask", "flask api", "flask framework"],
            "aws": ["aws", "amazon web services", "ec2", "s3", "lambda", "amazon aws"],
            "gcp": ["gcp", "google cloud", "google cloud platform", "gcloud"],
            "azure": ["azure", "microsoft azure", "ms azure", "windows azure"],
            "cloud platforms": ["cloud platforms", "cloud services", "cloud computing", "cloud infrastructure"],
            "spark": ["spark", "apache spark", "pyspark", "spark sql"],
            "hadoop": ["hadoop", "hdfs", "mapreduce", "apache hadoop"],
            "kafka": ["kafka", "apache kafka", "kafka streams"],
            "machine learning": ["machine learning", "ml", "scikit-learn", "sklearn", "ml models"],
            "deep learning": ["deep learning", "dl", "neural networks", "nn", "dnn"],
            "tensorflow": ["tensorflow", "tf", "tf2", "tensorflow 2"],
            "pytorch": ["pytorch", "torch", "py torch"],
            "docker": ["docker", "containers", "containerization", "dockerfile"],
            "kubernetes": ["kubernetes", "k8s", "kubectl", "k8", "container orchestration"],
            "graphql": ["graphql", "graph ql", "apollo", "graphql api"],
            "rest": ["rest", "restful", "rest api", "restful api", "rest services"],
            "rest apis": ["rest apis", "restful apis", "rest api", "restful api", "api development"],
            "git": ["git", "github", "gitlab", "bitbucket", "version control", "vcs"],
            "ci/cd": ["ci/cd", "cicd", "continuous integration", "continuous deployment", "jenkins", "travis", "circle ci"],
            "agile": ["agile", "scrum", "kanban", "sprint", "agile methodology"],
            "etl": ["etl", "elt", "extract transform load", "data pipeline", "data pipelines"],
            "data warehouse": ["data warehouse", "data warehousing", "dwh", "datawarehouse"],
            "apache spark": ["apache spark", "spark", "pyspark", "spark sql", "spark streaming"],
            "sql/nosql databases": ["sql/nosql", "sql nosql", "sql and nosql", "relational and non-relational", 
                                   "sql", "nosql", "mysql", "postgresql", "mongodb", "cassandra", "redis",
                                   "database", "databases", "rdbms", "nosql databases"],
        }
    
    def calculate_skill_match_score(self, resume_text: str, required_skills: List[str]) -> tuple[float, List[str], Dict[str, List[str]]]:
        """Calculate skill matching score with variations"""
        resume_lower = resume_text.lower()
        matched_skills = []
        detailed_matches = {}
        
        for skill in required_skills:
            skill_lower = skill.lower().strip()
            skill_matched = False
            
            if skill_lower in resume_lower:
                matched_skills.append(skill)
                detailed_matches[skill] = [skill_lower]
                skill_matched = True
                continue
            
            skill_key = None
            for key in self.skill_variations:
                if skill_lower in self.skill_variations[key] or key in skill_lower:
                    skill_key = key
                    break
            
            if skill_key and skill_key in self.skill_variations:
                variations_found = []
                for variation in self.skill_variations[skill_key]:
                    if variation in resume_lower:
                        variations_found.append(variation)
                        skill_matched = True
                
                if variations_found:
                    matched_skills.append(skill)
                    detailed_matches[skill] = variations_found
            
            if not skill_matched and ' ' in skill:
                parts = skill.split()
                if all(part.lower() in resume_lower for part in parts):
                    matched_skills.append(skill)
                    detailed_matches[skill] = [skill_lower]
        
        score = len(matched_skills) / len(required_skills) if required_skills else 0
        return score, matched_skills, detailed_matches
    
    def parse_experience_range(self, experience_str: str) -> tuple[int, int]:
        """Parse experience range like '5-8 years' to (5, 8)"""
        numbers = re.findall(r'\d+', experience_str)
        
        if len(numbers) >= 2:
            return int(numbers[0]), int(numbers[1])
        elif len(numbers) == 1:
            if '+' in experience_str:
                return int(numbers[0]), int(numbers[0]) + 5
            else:
                return int(numbers[0]), int(numbers[0])
        else:
            return 0, 100
    
    def calculate_experience_match(self, resume_text: str, required_experience: str) -> tuple[float, int]:
        """Calculate experience matching score"""
        min_req, max_req = self.parse_experience_range(required_experience)
        
        patterns = [
            r'(\d+)\+?\s*years?\s*(?:of\s*)?(?:professional\s*)?experience',
            r'experience\s*[:–-]\s*(\d+)\+?\s*years?',
            r'(\d+)\+?\s*years?\s*in\s*(?:software|data|engineering|development)',
            r'total\s*experience\s*[:–-]\s*(\d+)\+?\s*years?',
            r'(\d+)\+?\s*yrs?\s*exp',
            r'(\d{4})\s*[-–]\s*(?:present|current|now|(\d{4}))',
        ]
        
        date_patterns = [
            r'from\s+(?:january|february|march|april|may|june|july|august|september|october|november|december),?\s*(\d{4})\s*[-–]\s*(?:present|current|now)',
            r'(?:january|february|march|april|may|june|july|august|september|october|november|december),?\s*(\d{4})\s*[-–]\s*(?:january|february|march|april|may|june|july|august|september|october|november|december),?\s*(\d{4})',
            r'(\d{4})\s*(?:to|-|–)\s*(\d{4})',
            r'since\s+(?:january|february|march|april|may|june|july|august|september|october|november|december),?\s*(\d{4})',
        ]
        
        month_year_patterns = [
            r'(?:january|february|march|april|may|june|july|august|september|october|november|december),?\s*(\d{4})\s*[-–]\s*(?:present|current|now)',
            r'(?:jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*,?\s*(\d{4})\s*[-–]\s*(?:present|current|now)',
        ]
        
        years_found = []
        experience_periods = []
        
        education_keywords = ['education', 'academic', 'degree', 'bachelor', 'master', 'phd', 'university', 'college', 'school']
        
        for pattern in patterns:
            matches = re.findall(pattern, resume_text.lower())
            for match in matches:
                if isinstance(match, tuple):
                    if match[0].isdigit() and len(match[0]) == 4:
                        start_year = int(match[0])
                        if match[1] and match[1].isdigit():
                            end_year = int(match[1])
                        else:
                            end_year = datetime.now().year
                        
                        match_context = resume_text.lower()[max(0, resume_text.lower().find(match[0])-100):resume_text.lower().find(match[0])+100]
                        if not any(edu_keyword in match_context for edu_keyword in education_keywords):
                            if 1990 < start_year <= datetime.now().year:
                                years_found.append(end_year - start_year)
                else:
                    if match.isdigit():
                        years_found.append(int(match))
        
        experience_keywords = ['experience', 'work', 'employed', 'position', 'role', 'job', 'company', 'engineer at', 'developer at']
        
        for pattern in month_year_patterns:
            for match in re.finditer(pattern, resume_text.lower()):
                match_text = match.group(1) if match.groups() else match.group(0)
                if match_text.isdigit():
                    start_year = int(match_text)
                    
                    match_context = resume_text.lower()[max(0, match.start()-200):match.end()+50]
                    if any(exp_keyword in match_context for exp_keyword in experience_keywords):
                        if 1990 < start_year <= datetime.now().year:
                            current_year = datetime.now().year
                            current_month = datetime.now().month
                            
                            month_str = resume_text.lower()[max(0, match.start()-20):match.start()].strip()
                            
                            month_map = {
                                'january': 1, 'february': 2, 'march': 3, 'april': 4,
                                'may': 5, 'june': 6, 'july': 7, 'august': 8,
                                'september': 9, 'october': 10, 'november': 11, 'december': 12
                            }
                            
                            start_month = 1
                            for month_name, month_num in month_map.items():
                                if month_name in month_str:
                                    start_month = month_num
                                    break
                            
                            if start_year == current_year:
                                years = (current_month - start_month) / 12.0
                            elif start_year == current_year - 1:
                                years = 1 + ((current_month - start_month) / 12.0)
                            else:
                                years = current_year - start_year + ((current_month - start_month) / 12.0)
                            
                            experience_periods.append(max(0.5, years))
        
        for pattern in date_patterns:
            matches = re.findall(pattern, resume_text.lower())
            for match in matches:
                if isinstance(match, tuple):
                    if len(match) >= 1:
                        start_year = int(match[0])
                        if len(match) > 1 and match[1] and match[1].isdigit():
                            end_year = int(match[1])
                        else:
                            end_year = datetime.now().year
                        
                        match_context = resume_text.lower()[max(0, resume_text.lower().find(str(start_year))-100):resume_text.lower().find(str(start_year))+100]
                        if any(exp_keyword in match_context for exp_keyword in experience_keywords) and \
                           not any(edu_keyword in match_context for edu_keyword in education_keywords):
                            if 1990 < start_year <= datetime.now().year and end_year - start_year < 10:
                                experience_periods.append(end_year - start_year)
                elif match and match.isdigit():
                    start_year = int(match)
                    if 1990 < start_year <= datetime.now().year:
                        experience_periods.append(datetime.now().year - start_year)
        
        all_years = years_found + experience_periods
        
        if all_years:
            realistic_years = [y for y in all_years if 0 < y < 15]
            
            if realistic_years:
                candidate_years = max(realistic_years)
                if candidate_years < 1:
                    candidate_years = 1
                else:
                    candidate_years = int(round(candidate_years))
            else:
                candidate_years = int(round(max(all_years)))
            
            if min_req <= candidate_years <= max_req:
                return 1.0, candidate_years
            elif candidate_years > max_req:
                return 0.9, candidate_years
            elif candidate_years >= min_req - 1:
                return 0.8, candidate_years
            else:
                return candidate_years / min_req if min_req > 0 else 0, candidate_years
        
        return 0.0, 0
    
    def score_resume(self, resume_text: str, job_ticket: EnhancedJobTicket) -> Dict[str, Any]:
        """Enhanced score_resume method with professional development"""
        
        skill_score, matched_skills, detailed_matches = self.calculate_skill_match_score(
            resume_text, job_ticket.tech_stack
        )
        
        exp_score, detected_years = self.calculate_experience_match(
            resume_text, job_ticket.experience_required
        )
        
        location_score = 0.0
        if job_ticket.location.lower() in resume_text.lower():
            location_score = 1.0
        elif "remote" in job_ticket.location.lower() or "remote" in resume_text.lower():
            location_score = 0.8
        
        pd_results = self.pd_scorer.calculate_professional_development_score(resume_text)
        
        weights = {
            'skills': 0.40,
            'experience': 0.30,
            'location': 0.10,
            'professional_dev': 0.20
        }
        
        final_score = (
            weights['skills'] * skill_score +
            weights['experience'] * exp_score +
            weights['location'] * location_score +
            weights['professional_dev'] * pd_results['professional_development_score']
        )
        
        return {
            'final_score': final_score,
            'skill_score': skill_score,
            'experience_score': exp_score,
            'location_score': location_score,
            'professional_development_score': pd_results['professional_development_score'],
            'matched_skills': matched_skills,
            'detailed_skill_matches': detailed_matches,
            'detected_experience_years': detected_years,
            'professional_development': pd_results,
            'scoring_weights': weights,
            'job_requirements': {
                'position': job_ticket.position,
                'required_skills': job_ticket.tech_stack,
                'required_experience': job_ticket.experience_required,
                'location': job_ticket.location
            }
        }


class UpdateAwareBasicFilter:
    """Enhanced basic filter with comprehensive scoring and duplicate detection"""
    
    def __init__(self):
        self.resume_filter = UpdateAwareResumeFilter()
        self.duplicate_detector = DuplicateCandidateDetector()
        self.duplicate_handler = DuplicateHandlingStrategy()
        
        try:
            self.nlp = spacy.load("en_core_web_sm")
        except:
            os.system("python -m spacy download en_core_web_sm")
            self.nlp = spacy.load("en_core_web_sm")
        
        self.vectorizer = TfidfVectorizer(
            max_features=500,
            stop_words='english',
            ngram_range=(1, 2)
        )
    
    def score_resume_comprehensive(self, resume_text: str, resume_path: Path, job_ticket: EnhancedJobTicket) -> Dict:
        """Comprehensive scoring using multiple methods"""
        base_scores = self.resume_filter.score_resume(resume_text, job_ticket)
        
        similarity_score = 0.0
        if job_ticket.description:
            try:
                tfidf_matrix = self.vectorizer.fit_transform([job_ticket.description, resume_text])
                similarity_score = cosine_similarity(tfidf_matrix[0:1], tfidf_matrix[1:2])[0][0]
            except:
                similarity_score = 0.0
        
        additional_features = self._extract_additional_features(resume_text)
        
        result = {
            "file_path": str(resume_path),
            "filename": resume_path.name,
            "final_score": base_scores['final_score'],
            "skill_score": base_scores['skill_score'],
            "experience_score": base_scores['experience_score'],
            "location_score": base_scores['location_score'],
            "professional_development_score": base_scores['professional_development_score'],
            "similarity_score": similarity_score,
            "matched_skills": base_scores['matched_skills'],
            "detailed_skill_matches": base_scores['detailed_skill_matches'],
            "detected_experience_years": base_scores['detected_experience_years'],
            "professional_development": base_scores['professional_development'],
            "additional_features": additional_features,
            "scoring_weights": base_scores['scoring_weights'],
            "job_requirements_used": base_scores['job_requirements']
        }
        
        return result
    
    def _extract_additional_features(self, resume_text: str) -> Dict:
        """Extract additional features from resume"""
        features = {}
        
        education_keywords = {
            'phd': 4, 'doctorate': 4,
            'master': 3, 'mba': 3, 'ms': 3, 'mtech': 3,
            'bachelor': 2, 'btech': 2, 'bs': 2, 'be': 2,
            'diploma': 1
        }
        
        resume_lower = resume_text.lower()
        education_score = 0
        for keyword, score in education_keywords.items():
            if keyword in resume_lower:
                education_score = max(education_score, score)
        
        features['education_level'] = education_score
        
        cert_keywords = ['certified', 'certification', 'certificate', 'aws certified', 'google certified', 'microsoft certified']
        features['has_certifications'] = any(cert in resume_lower for cert in cert_keywords)
        
        leadership_keywords = ['lead', 'manager', 'head', 'director', 'principal', 'senior', 'architect']
        features['leadership_experience'] = sum(1 for keyword in leadership_keywords if keyword in resume_lower)
        
        return features


class UpdatedResumeFilteringSystem:
    """Complete resume filtering system WITHOUT LLM - Pure algorithmic approach"""
    
    def __init__(self, ticket_folder: str):
        self.ticket_folder = Path(ticket_folder)
        self.job_ticket = EnhancedJobTicket(ticket_folder)
        self.basic_filter = UpdateAwareBasicFilter()
        
        self.output_folder = self.ticket_folder / "filtering_results"
        self.output_folder.mkdir(exist_ok=True)
    
    def filter_resumes(self) -> Dict:
        """Main filtering method with pure algorithmic approach"""
        print(f"\n{'='*70}")
        print(f"🚀 RESUME FILTERING SYSTEM (NO LLM)")
        print(f"{'='*70}")
        print(f"Job Ticket: {self.job_ticket.ticket_id}")
        print(f"Position: {self.job_ticket.position}")
        print(f"\n📋 JOB REQUIREMENTS:")
        print(f"  • Experience: {self.job_ticket.experience_required}")
        print(f"  • Skills: {', '.join(self.job_ticket.tech_stack)}")
        print(f"  • Location: {self.job_ticket.location}")
        print(f"  • Salary: {self.job_ticket.salary_range}")
        print(f"  • Deadline: {self.job_ticket.deadline}")
        print(f"{'='*70}\n")
        
        resumes = self.job_ticket.get_resumes()
        print(f"📄 Found {len(resumes)} resumes to process")
        
        if not resumes:
            return {
                "error": "No resumes found in the ticket folder",
                "ticket_id": self.job_ticket.ticket_id
            }
        
        print("\n🔍 Stage 1: Algorithmic Filtering with Duplicate Detection...")
        initial_results = self._basic_filtering_with_duplicates(resumes)
        
        with open(self.output_folder / "stage1_results.json", 'w') as f:
            json.dump(initial_results, f, indent=2, default=str)
        
        print("\n🧮 Stage 2: Advanced Scoring and Ranking...")
        final_results = self._advanced_scoring(initial_results)
        
        with open(self.output_folder / "final_results.json", 'w') as f:
            json.dump(final_results, f, indent=2, default=str)
        
        final_output = {
            "ticket_id": self.job_ticket.ticket_id,
            "position": self.job_ticket.position,
            "timestamp": datetime.now().isoformat(),
            "job_status": self.job_ticket.job_details.get('status', 'unknown'),
            "requirements_last_updated": self.job_ticket.job_details.get('last_updated', ''),
            "latest_requirements": {
                "experience": self.job_ticket.experience_required,
                "tech_stack": self.job_ticket.tech_stack,
                "location": self.job_ticket.location,
                "salary": self.job_ticket.salary_range,
                "deadline": self.job_ticket.deadline
            },
            "summary": {
                "total_resumes": len(resumes),
                "unique_candidates": initial_results.get('unique_candidates', len(resumes)),
                "duplicate_groups_found": initial_results.get('duplicate_groups_count', 0),
                "stage1_selected": len(initial_results["top_10"]),
                "final_selected": len(final_results.get("top_5_candidates", [])),
            },
            "duplicate_detection": initial_results.get('duplicate_summary', {}),
            "stage1_results": initial_results,
            "final_results": final_results,
            "final_top_5": final_results.get("top_5_candidates", []),
        }
        
        output_file = self.output_folder / f"final_results_{self.job_ticket.ticket_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json"
        with open(output_file, 'w') as f:
            json.dump(final_output, f, indent=2, default=str)
        
        self._create_enhanced_summary_report(final_output)
        
        print(f"\n✅ Filtering complete! Results saved to: {output_file}")
        
        return final_output
    
    def _basic_filtering_with_duplicates(self, resumes: List[Path]) -> Dict:
        """Stage 1 with duplicate detection and handling"""
        
        print("\n🔍 Detecting duplicate candidates...")
        
        duplicate_map = {}
        
        for resume_path in resumes:
            resume_text = ResumeExtractor.extract_text(resume_path)
            if not resume_text:
                continue
            
            candidate_id, duplicates = self.basic_filter.duplicate_detector.add_candidate(
                resume_text, resume_path.name
            )
            
            duplicate_map[resume_path.name] = {
                'candidate_id': candidate_id,
                'duplicates': duplicates
            }
            
            if duplicates:
                print(f"  ⚠️ {resume_path.name} has {len(duplicates)} duplicate(s):")
                for dup in duplicates:
                    print(f"     - {dup['filename']} (confidence: {dup['confidence']:.1%}, reason: {dup['reason']})")
        
        dup_groups = self.basic_filter.duplicate_detector.get_duplicate_groups()
        
        print("\n📊 Scoring resumes...")
        scored_resumes = []
        processed_candidates = set()
        
        for i, resume_path in enumerate(resumes):
            print(f"  Processing {i+1}/{len(resumes)}: {resume_path.name}")
            
            resume_text = ResumeExtractor.extract_text(resume_path)
            if not resume_text:
                print(f"    ⚠️ Failed to extract text from {resume_path.name}")
                continue
            
            candidate_info = duplicate_map.get(resume_path.name, {})
            candidate_id = candidate_info.get('candidate_id')
            
            score_result = self.basic_filter.score_resume_comprehensive(
                resume_text, 
                resume_path,
                self.job_ticket
            )
            
            score_result['candidate_id'] = candidate_id
            
            if candidate_info.get('duplicates'):
                score_result['has_duplicates'] = True
                score_result['duplicate_count'] = len(candidate_info['duplicates'])
                score_result['duplicates'] = candidate_info['duplicates']
            else:
                score_result['has_duplicates'] = False
            
            scored_resumes.append(score_result)
        
        final_scored_resumes = self._merge_duplicate_scores(scored_resumes, dup_groups)
        
        final_scored_resumes.sort(key=lambda x: x["final_score"], reverse=True)
        top_10 = final_scored_resumes[:10]
        
        print("\n📊 Top Candidates (after duplicate handling):")
        for i, candidate in enumerate(top_10[:min(len(top_10), 5)]):
            print(f"  {i+1}. {candidate['filename']} - Score: {candidate['final_score']:.2%}")
            print(f"      Skills: {len(candidate['matched_skills'])}/{len(self.job_ticket.tech_stack)} matched")
            print(f"      Experience: {candidate['detected_experience_years']} years")
            print(f"      Prof. Development: {candidate['professional_development_score']:.2%}")
            if candidate.get('has_duplicates'):
                print(f"      ⚠️ Best of {candidate.get('duplicate_count', 1) + 1} submissions")
        
        duplicate_summary = {
            "total_resumes_submitted": len(resumes),
            "unique_candidates": len(final_scored_resumes),
            "duplicate_groups_found": len(dup_groups),
            "duplicate_groups": [
                {
                    "group_size": len(group),
                    "filenames": [item['filename'] for item in group]
                }
                for group in dup_groups
            ]
        }
        
        print(f"\n📊 Duplicate Detection Summary:")
        print(f"  Total resumes submitted: {duplicate_summary['total_resumes_submitted']}")
        print(f"  Unique candidates: {duplicate_summary['unique_candidates']}")
        print(f"  Duplicate groups found: {duplicate_summary['duplicate_groups_found']}")
        
        return {
            "all_resumes": final_scored_resumes,
            "top_10": top_10,
            "scoring_criteria": {
                "skills_required": self.job_ticket.tech_stack,
                "experience_range": self.job_ticket.experience_required,
                "location": self.job_ticket.location
            },
            "duplicate_summary": duplicate_summary,
            "unique_candidates": len(final_scored_resumes),
            "duplicate_groups_count": len(dup_groups)
        }
    
    def _merge_duplicate_scores(self, scored_resumes: List[Dict], dup_groups: List[List[Dict]]) -> List[Dict]:
        """Merge scores for duplicate candidates"""
        
        id_to_resumes = defaultdict(list)
        for resume in scored_resumes:
            if resume.get('candidate_id'):
                id_to_resumes[resume['candidate_id']].append(resume)
        
        final_results = []
        processed_ids = set()
        
        for group in dup_groups:
            group_candidate_ids = [item['candidate_id'] for item in group]
            group_resumes = []
            
            for cid in group_candidate_ids:
                if cid in id_to_resumes:
                    group_resumes.extend(id_to_resumes[cid])
            
            if group_resumes:
                merged_candidate = self.basic_filter.duplicate_handler.merge_scores(group_resumes)
                final_results.append(merged_candidate)
                
                for cid in group_candidate_ids:
                    processed_ids.add(cid)
        
        for resume in scored_resumes:
            cid = resume.get('candidate_id')
            if cid and cid not in processed_ids:
                final_results.append(resume)
                processed_ids.add(cid)
            elif not cid:
                final_results.append(resume)
        
        return final_results
    
    def _advanced_scoring(self, initial_results: Dict) -> Dict:
        """Stage 2: Advanced algorithmic scoring without LLM"""
        top_10 = initial_results["top_10"]
        
        # Apply additional scoring criteria
        for candidate in top_10:
            # Bonus for exact skill matches
            exact_matches = sum(1 for skill in self.job_ticket.tech_stack 
                              if skill.lower() in candidate['filename'].lower())
            candidate['exact_skill_bonus'] = exact_matches * 0.05
            
            # Bonus for certifications
            if candidate.get('additional_features', {}).get('has_certifications'):
                candidate['certification_bonus'] = 0.1
            else:
                candidate['certification_bonus'] = 0
            
            # Bonus for leadership experience
            leadership_score = candidate.get('additional_features', {}).get('leadership_experience', 0)
            candidate['leadership_bonus'] = min(leadership_score * 0.02, 0.1)
            
            # Recalculate final score with bonuses
            candidate['adjusted_score'] = min(
                candidate['final_score'] + 
                candidate['exact_skill_bonus'] + 
                candidate['certification_bonus'] + 
                candidate['leadership_bonus'],
                1.0
            )
        
        # Re-sort by adjusted score
        top_10.sort(key=lambda x: x['adjusted_score'], reverse=True)
        
        # Select top 5
        top_5_candidates = []
        for i, candidate in enumerate(top_10[:min(5, len(top_10))]):
            candidate['final_rank'] = i + 1
            candidate['selection_reason'] = self._generate_selection_reason(candidate)
            top_5_candidates.append(candidate)
        
        return {
            "top_5_candidates": top_5_candidates,
            "selection_criteria": "Algorithmic scoring based on skills, experience, professional development, and additional features",
            "scoring_method": "Pure algorithmic approach without LLM"
        }
    
    def _generate_selection_reason(self, candidate: Dict) -> str:
        """Generate selection reason based on scores"""
        reasons = []
        
        if candidate['skill_score'] >= 0.8:
            reasons.append("Excellent skill match")
        elif candidate['skill_score'] >= 0.6:
            reasons.append("Good skill match")
        else:
            reasons.append("Moderate skill match")
        
        if candidate['experience_score'] >= 0.9:
            reasons.append("perfect experience fit")
        elif candidate['experience_score'] >= 0.7:
            reasons.append("good experience level")
        
        if candidate['professional_development_score'] >= 0.6:
            reasons.append("strong professional development")
        
        if candidate.get('certification_bonus', 0) > 0:
            reasons.append("has relevant certifications")
        
        if candidate.get('leadership_bonus', 0) > 0:
            reasons.append("leadership experience")
        
        return "; ".join(reasons).capitalize()
    
    def _create_enhanced_summary_report(self, results: Dict):
        """Create detailed summary report"""
        report_path = self.output_folder / f"summary_report_{self.job_ticket.ticket_id}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.txt"
        
        with open(report_path, 'w') as f:
            f.write(f"RESUME FILTERING SUMMARY REPORT (NO LLM)\n")
            f.write(f"{'='*70}\n\n")
            f.write(f"Job Ticket ID: {results['ticket_id']}\n")
            f.write(f"Position: {results['position']}\n")
            f.write(f"Report Generated: {results['timestamp']}\n")
            
            f.write(f"\n{'='*70}\n")
            f.write(f"JOB REQUIREMENTS:\n")
            f.write(f"{'='*70}\n")
            f.write(f"Experience: {results['latest_requirements']['experience']}\n")
            f.write(f"Skills: {', '.join(results['latest_requirements']['tech_stack'])}\n")
            f.write(f"Location: {results['latest_requirements']['location']}\n")
            f.write(f"Salary: {results['latest_requirements']['salary']}\n")
            f.write(f"Deadline: {results['latest_requirements']['deadline']}\n")
            
            f.write(f"\n{'='*70}\n")
            f.write(f"FILTERING SUMMARY:\n")
            f.write(f"{'='*70}\n")
            f.write(f"Total Resumes Submitted: {results['summary']['total_resumes']}\n")
            f.write(f"Unique Candidates: {results['summary']['unique_candidates']}\n")
            f.write(f"Duplicate Groups Found: {results['summary']['duplicate_groups_found']}\n")
            f.write(f"Final Selected: {results['summary']['final_selected']}\n")
            
            if results.get('duplicate_detection') and results['duplicate_detection'].get('duplicate_groups'):
                f.write(f"\n{'='*70}\n")
                f.write(f"DUPLICATE CANDIDATES DETECTED:\n")
                f.write(f"{'='*70}\n")
                for i, group in enumerate(results['duplicate_detection']['duplicate_groups'], 1):
                    f.write(f"\nGroup {i} ({group['group_size']} submissions):\n")
                    for filename in group['filenames']:
                        f.write(f"  - {filename}\n")
            
            f.write(f"\n{'='*70}\n")
            f.write(f"TOP CANDIDATES (RANKED):\n")
            f.write(f"{'='*70}\n\n")
            
            for i, candidate in enumerate(results['final_top_5']):
                f.write(f"{i+1}. {candidate['filename']}\n")
                f.write(f"   Overall Score: {candidate.get('adjusted_score', candidate['final_score']):.1%}\n")
                f.write(f"   Skill Match: {candidate['skill_score']:.1%} ({len(candidate['matched_skills'])}/{len(results['latest_requirements']['tech_stack'])} skills)\n")
                f.write(f"   Matched Skills: {', '.join(candidate['matched_skills'])}\n")
                f.write(f"   Experience: {candidate['detected_experience_years']} years (Score: {candidate['experience_score']:.1%})\n")
                f.write(f"   Location Match: {'Yes' if candidate['location_score'] > 0 else 'No'}\n")
                f.write(f"   Professional Development Score: {candidate['professional_development_score']:.1%}\n")
                f.write(f"   Selection Reason: {candidate.get('selection_reason', 'N/A')}\n")
                
                if candidate.get('has_duplicates'):
                    f.write(f"   ⚠️ DUPLICATE: Best of {candidate.get('duplicate_count', 1) + 1} submissions\n")
                
                f.write(f"\n")
        
        print(f"\n📄 Summary report created: {report_path}")


def main():
    """Main function for running the resume filter without LLM"""
    import sys
    import argparse
    
    parser = argparse.ArgumentParser(description='Resume Filtering System WITHOUT LLM')
    parser.add_argument('ticket_folder', help='Path to the ticket folder containing resumes and job details')
    
    args = parser.parse_args()
    
    if not os.path.exists(args.ticket_folder):
        print(f"❌ Error: Folder '{args.ticket_folder}' not found")
        return
    
    try:
        print("🚀 Initializing Resume Filtering System (No LLM Required)...")
        filter_system = UpdatedResumeFilteringSystem(args.ticket_folder)
        
        results = filter_system.filter_resumes()
        
        if "error" not in results:
            print(f"\n{'='*70}")
            print(f"✅ FILTERING COMPLETE - FINAL SUMMARY")
            print(f"{'='*70}")
            print(f"Total resumes processed: {results['summary']['total_resumes']}")
            print(f"Unique candidates identified: {results['summary']['unique_candidates']}")
            print(f"Duplicate groups found: {results['summary']['duplicate_groups_found']}")
            print(f"\nTop candidates:")
            for i, candidate in enumerate(results['final_top_5']):
                print(f"  {i+1}. {candidate['filename']}")
                print(f"      Score: {candidate.get('adjusted_score', candidate['final_score']):.1%}")
                print(f"      Skills: {len(candidate['matched_skills'])}/{len(results['latest_requirements']['tech_stack'])} matched")
                print(f"      Experience: {candidate['detected_experience_years']} years")
                print(f"      Prof. Development: {candidate['professional_development_score']:.1%}")
                if candidate.get('has_duplicates'):
                    print(f"      ⚠️ Best of {candidate.get('duplicate_count', 1) + 1} submissions")
            
            print(f"\n📁 Results saved in: {filter_system.output_folder}")
        else:
            print(f"\n❌ Error: {results['error']}")
    
    except Exception as e:
        print(f"\n❌ Error: {str(e)}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()