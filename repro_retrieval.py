import requests
import json

BASE_URL = "http://127.0.0.1:8085"

def main():
    try:
        # 1. Get Project ID
        print("Fetching projects...")
        resp = requests.get(f"{BASE_URL}/projects")
        resp.raise_for_status()
        data = resp.json()
        projects = data["projects"]
        if isinstance(projects, str):
            projects = json.loads(projects)
        if not projects:
            print("No projects found.")
            return
        
        project_id = projects[0]["project_id"]
        print(f"Using project_id: {project_id}")

        # 2. Send Retrieval Query
        print("Sending retrieval query...")
        payload = {
            "project_id": project_id,
            "query": "something to search",
            "k": 5
        }
        resp = requests.post(f"{BASE_URL}/query/retrieval", json=payload)
        print(f"Status Code: {resp.status_code}")
        print("Response:", resp.text)

    except Exception as e:
        print(f"Error: {e}")

if __name__ == "__main__":
    main()
