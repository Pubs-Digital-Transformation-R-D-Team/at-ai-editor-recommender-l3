"""Quick smoke test for Jira API connectivity."""
import json
from jira_client import server_info, myself, list_projects, search_issues, my_open_issues

print("=" * 50)
print("JIRA MCP SERVER — CONNECTION TEST")
print("=" * 50)

# Test 1: Server info (always works)
print("\n1. Testing server_info ...")
try:
    info = json.loads(server_info())
    print(f"   URL: {info['url']}")
    print(f"   Version: {info['version']}")
    print(f"   Deployment: {info['deployment']}")
    print("   ✅ Connection OK!")
except Exception as e:
    print(f"   ❌ ERROR: {e}")

# Test 2: Who am I?
print("\n2. Testing myself ...")
try:
    me = json.loads(myself())
    if "error" in me:
        print(f"   ⚠️ {me['error']}")
        print(f"   Hint: {me.get('hint', '')}")
    else:
        print(f"   Name: {me['name']}")
        print(f"   Email: {me['email']}")
except Exception as e:
    print(f"   ❌ ERROR: {e}")

# Test 3: List projects
print("\n3. Testing list_projects ...")
try:
    projects = json.loads(list_projects())
    print(f"   Found {len(projects)} project(s)")
    for p in projects[:10]:
        print(f"   - {p['key']}: {p['name']} ({p['type']})")
    if not projects:
        print("   ⚠️ No projects visible — your token may have limited scope")
except Exception as e:
    print(f"   ❌ ERROR: {e}")

# Test 4: Search issues (bounded query)
print("\n4. Testing search_issues (bounded) ...")
try:
    # First try to find any project key from the list
    projects = json.loads(list_projects())
    if projects:
        key = projects[0]["key"]
        print(f"   Using project: {key}")
        result = json.loads(search_issues(jql=f"project = {key} ORDER BY updated DESC", max_results=5))
    else:
        # Fallback: try a broad but bounded query
        result = json.loads(search_issues(jql="updated >= -30d ORDER BY updated DESC", max_results=5))

    if "error" in result:
        print(f"   ⚠️ {result['error']}")
        print(f"   Hint: {result.get('hint', '')}")
    else:
        print(f"   Total: {result['total']} | Showing: {result['showing']}")
        for i in result.get("issues", []):
            print(f"   - {i['key']}: {i['summary'][:60]} [{i['status']}]")
except Exception as e:
    print(f"   ❌ ERROR: {e}")

# Test 5: My issues
print("\n5. Testing my_open_issues ...")
try:
    result = json.loads(my_open_issues())
    if "error" in result:
        print(f"   ⚠️ {result['error']}")
    else:
        print(f"   Total: {result['total']} | Showing: {result['showing']}")
        for i in result.get("issues", []):
            print(f"   - {i['key']}: {i['summary'][:60]} [{i['status']}]")
        if result['total'] == 0:
            print("   (No open issues assigned to you)")
except Exception as e:
    print(f"   ❌ ERROR: {e}")

print("\n" + "=" * 50)
print("DONE")
