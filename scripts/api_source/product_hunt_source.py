import os
import sys
import csv
import time
import requests

# Add the scripts directory to sys.path to allow importing db_helper later
sys.path.append(os.path.abspath(os.path.join(os.path.dirname(__file__), "..")))

import db_helper

def load_env(env_path=".env"):
    """Simple helper to load key-value pairs from .env file."""
    env_vars = {}
    # Check current directory and parents up to two levels
    paths_to_check = [
        env_path,
        os.path.join("..", env_path),
        os.path.join("..", "..", env_path),
        os.path.join(os.path.dirname(__file__), "..", "..", env_path)
    ]
    for path in paths_to_check:
        if os.path.exists(path):
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line or line.startswith("#"):
                        continue
                    if "=" in line:
                        key, val = line.split("=", 1)
                        # Remove comments at the end of the line if any
                        if "#" in val:
                            val = val.split("#", 1)[0]
                        env_vars[key.strip()] = val.strip()
            break
    return env_vars

def fetch_product_hunt_posts(api_key, target_count=200):
    url = "https://api.producthunt.com/v2/api/graphql"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    query = """
    query ($cursor: String) {
      posts(first: 20, after: $cursor) {
        edges {
          node {
            name
            website
            topics(first: 5) {
              edges {
                node {
                  name
                }
              }
            }
          }
          cursor
        }
        pageInfo {
          hasNextPage
          endCursor
        }
      }
    }
    """

    posts = []
    cursor = None
    has_next = True
    page = 1

    print(f"Starting fetch from Product Hunt API for {target_count} posts...")

    while has_next and len(posts) < target_count:
        print(f"Fetching page {page} with cursor: {cursor}...")
        variables = {"cursor": cursor}
        
        try:
            response = requests.post(
                url, 
                json={"query": query, "variables": variables}, 
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            res_data = response.json()
            
            if "errors" in res_data:
                print(f"GraphQL Errors: {res_data['errors']}")
                break
                
            data = res_data.get("data", {})
            posts_connection = data.get("posts", {})
            edges = posts_connection.get("edges", [])
            
            for edge in edges:
                node = edge.get("node", {})
                if not node:
                    continue
                # Extract topics
                topic_edges = node.get("topics", {}).get("edges", [])
                topics = [t.get("node", {}).get("name") for t in topic_edges if t.get("node", {}).get("name")]
                sector = ", ".join(topics) if topics else None
                
                posts.append({
                    "Company_name": node.get("name"),
                    "Website": node.get("website"),
                    "Sector": sector,
                    "Country": None,
                    "Source": "Product Hunt",
                    "Active": True,
                    "No_of_employees": None
                })
                
            page_info = posts_connection.get("pageInfo", {})
            has_next = page_info.get("hasNextPage", False)
            cursor = page_info.get("endCursor")
            page += 1
            
            # Avoid hitting rate limits
            time.sleep(0.5)
            
        except Exception as e:
            print(f"Error fetching data: {e}")
            break

    print(f"Fetched {len(posts)} posts total.")
    return posts[:target_count]

def main():
    # Load env variables to get API key
    env_vars = load_env()
    api_key = env_vars.get("PRODUCT_HUNT_KEY")
    if not api_key:
        print("Error: PRODUCT_HUNT_KEY not found in env variables or .env file.")
        sys.exit(1)
        
    posts = fetch_product_hunt_posts(api_key, 200)
    
    if not posts:
        print("No posts fetched. Exiting.")
        sys.exit(1)
        
    print("Upserting posts to Postgres database...")
    db_helper.upsert_companies(posts)
    print("Successfully completed data loading.")

if __name__ == "__main__":
    main()
