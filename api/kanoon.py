import requests
import os
from dotenv import load_dotenv

load_dotenv()

class KanoonClient:
    def __init__(self):
        self.api_key = os.getenv("KANOON_API_KEY")
        self.base_url = "https://api.indiankanoon.org/search/"

    def search_precedents(self, incident_type, state):
        """Fetches live results from Indian Kanoon API."""
        
        # If no key is present, we cannot make the call.
        if not self.api_key:
            print("ERROR: KANOON_API_KEY is missing from .env")
            return []

        # Constructing a broad but relevant insurance-focused query
        query = f"{incident_type} insurance claim liability"
        if state:
            query += f" {state}"

        auth_headers = {
            'Authorization': f'Token {self.api_key}',
            'Accept': 'application/json'
        }

        try:
            # Indian Kanoon API expects a POST with formInput
            params = {
                'formInput': query,
                'pagenum': 0
            }
            
            response = requests.post(
                self.base_url, 
                headers=auth_headers, 
                params=params, 
                timeout=10
            )
            
            if response.status_code == 200:
                data = response.json()
                # Document list is under 'docs'
                docs = data.get('docs', [])
                
                results = []
                for doc in docs[:3]: # Retrieve top 3 live cases
                    results.append({
                        "title": doc.get("title"),
                        "docid": str(doc.get("tid")),
                        "headline": doc.get("headline", "Legal precedent on claim liability.")
                    })
                return results
            
            print(f"Kanoon API Status Error: {response.status_code} - {response.text}")
            return []

        except Exception as e:
            print(f"Kanoon Connection Error: {e}")
            return []