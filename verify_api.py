import urllib.request
import urllib.parse
import json
import sys

base = 'http://127.0.0.1:8000'

def get(path, token=None):
    headers = {}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    req = urllib.request.Request(base + path, headers=headers)
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read().decode())

def post_json(path, payload, token=None):
    headers = {'Content-Type': 'application/json'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = json.dumps(payload).encode()
    req = urllib.request.Request(base + path, data=data, headers=headers, method='POST')
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read().decode())

def post_form(path, fields, token=None):
    headers = {'Content-Type': 'application/x-www-form-urlencoded'}
    if token:
        headers['Authorization'] = 'Bearer ' + token
    data = urllib.parse.urlencode(fields).encode()
    req = urllib.request.Request(base + path, data=data, headers=headers, method='POST')
    r = urllib.request.urlopen(req, timeout=10)
    return json.loads(r.read().decode())

print("=" * 60)
print("LIVE API VERIFICATION")
print("=" * 60)

# 1. Health check
try:
    result = get('/health')
    print("PASS  GET /health =>", result)
except Exception as e:
    print("FAIL  GET /health =>", e)

# 2. Login
token = None
try:
    result = post_form('/token', {'username': 'admin', 'password': 'admin123'})
    token = result.get('access_token', '')
    print("PASS  POST /token => Got JWT token (len=%d)" % len(token))
except Exception as e:
    print("FAIL  POST /token =>", e)
    sys.exit(1)

# 3. GET /clients
try:
    clients = get('/clients', token)
    names = [c['name'] for c in clients]
    print("PASS  GET /clients => %d clients: %s" % (len(clients), names))
except Exception as e:
    print("FAIL  GET /clients =>", e)

# 4. POST /clients (JSON body)
try:
    result = post_json('/clients', {'name': 'VerifyTest Corp', 'industry': 'Fintech'}, token)
    print("PASS  POST /clients => Created:", result)
    new_client_id = result.get('id')
except Exception as e:
    print("FAIL  POST /clients =>", e)
    new_client_id = None

# 5. GET /clients again - should show new one
try:
    clients = get('/clients', token)
    names = [c['name'] for c in clients]
    print("PASS  GET /clients (after add) => %d clients: %s" % (len(clients), names))
except Exception as e:
    print("FAIL  GET /clients (after add) =>", e)

# 6. GET /jds
try:
    jds = get('/jds', token)
    print("PASS  GET /jds => %d JDs found" % len(jds))
except Exception as e:
    print("FAIL  GET /jds =>", e)

# 7. GET /jds?client_id=<default>
default_client_id = '60e80ea2-ae7f-46d6-b30d-f73293036729'
try:
    jds = get('/jds?client_id=' + default_client_id, token)
    print("PASS  GET /jds?client_id=<default> => %d JDs" % len(jds))
    jd_id = jds[0]['id'] if jds else None
except Exception as e:
    print("FAIL  GET /jds?client_id= =>", e)
    jd_id = None

# 8. GET /match/by-jd/<jd_id> (if we have a JD)
if jd_id:
    try:
        matches = get('/match/by-jd/' + jd_id, token)
        print("PASS  GET /match/by-jd/<jd_id> => %d candidates registered" % len(matches))
    except Exception as e:
        print("FAIL  GET /match/by-jd/<jd_id> =>", e)
else:
    print("SKIP  GET /match/by-jd/<jd_id> (no JDs found in DB)")

print("=" * 60)
print("VERIFICATION COMPLETE")
print("=" * 60)
