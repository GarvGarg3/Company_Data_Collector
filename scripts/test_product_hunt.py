import os
import sys
import csv
import requests

def load_env(env_path=".env"):
    """Simple helper to load key-value pairs from .env file."""
    env_vars = {}
    paths_to_check = [
        env_path,
        os.path.join("..", env_path),
        os.path.join("..", "..", env_path),
        os.path.join(os.path.dirname(__file__), "..", env_path),
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
                        if "#" in val:
                            val = val.split("#", 1)[0]
                        env_vars[key.strip()] = val.strip()
            break
    return env_vars

def main():
    env_vars = load_env()
    api_key = env_vars.get("PRODUCT_HUNT_KEY") or os.getenv("PRODUCT_HUNT_KEY")
    if not api_key:
        print("Error: PRODUCT_HUNT_KEY not found in env variables or .env file.")
        sys.exit(1)

    url = "https://api.producthunt.com/v2/api/graphql"
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
        "Accept": "application/json"
    }

    query = """
    query {
      posts(first: 5) {
        edges {
          node {
            name
            website
            tagline
          }
        }
      }
    }
    """

    print("Sending test request to Product Hunt API...")
    try:
        response = requests.post(
            url, 
            json={"query": query}, 
            headers=headers,
            timeout=15
        )
        print(f"HTTP Status Code: {response.status_code}")
        print("Response Headers:")
        for k, v in response.headers.items():
            if k.lower().startswith("x-rate-limit") or k.lower() in ("retry-after", "content-type", "server"):
                print(f"  {k}: {v}")
        
        if response.status_code == 200:
            res_data = response.json()
            if "errors" in res_data:
                print("GraphQL Errors found in response:")
                print(res_data["errors"])
                sys.exit(1)
                
            data = res_data.get("data", {})
            edges = data.get("posts", {}).get("edges", [])
            print(f"Successfully retrieved {len(edges)} posts.")
            
            output_file = os.path.join(os.path.dirname(__file__), "product_hunt_test_output.csv")
            with open(output_file, "w", newline="", encoding="utf-8") as f:
                writer = csv.writer(f)
                writer.writerow(["Company_name", "Website", "Tagline"])
                for edge in edges:
                    node = edge.get("node", {})
                    writer.writerow([node.get("name"), node.get("website"), node.get("tagline")])
            print(f"Saved outputs to {output_file}")
        else:
            print(f"Request failed with status code {response.status_code}")
            print(response.text)
    except Exception as e:
        print(f"Exception raised during request: {e}")

if __name__ == "__main__":
    main()
