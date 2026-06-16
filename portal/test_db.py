import sys
import os

from database_service import DatabaseService

try:
    comps = DatabaseService.get_all_companies()
    print(f"Loaded {len(comps)} companies")
    if len(comps) > 0:
        print(f"First company: {comps[0]['razonSocial']}")
except Exception as e:
    print(f"Error: {e}")
