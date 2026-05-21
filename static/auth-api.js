/** Attach Bearer token from login (stored in localStorage). */

function getAuthHeaders(extraHeaders = {}) {

  const headers = { ...extraHeaders };

  const token = localStorage.getItem('token');

  if (token) {

    headers['Authorization'] = `Bearer ${token}`;

  }

  return headers;

}



/** Redirect to login if no token. Returns false if redirecting. */

function requireAuth(loginPath = '/login') {

  if (!localStorage.getItem('token')) {

    const base = getApiBase();

    window.location.href = loginPath.startsWith('http') ? loginPath : `${base}${loginPath}`;

    return false;

  }

  return true;

}



/**

 * Hiring FastAPI always runs on port 8001 locally.

 * (Port 8000 is often Django or a hint server — do not send API calls there.)

 */

function getApiBase() {

  const host = window.location.hostname;

  if (host === '127.0.0.1' || host === 'localhost') {

    return `http://${host}:8001`;

  }

  const pagePort = window.location.port;

  if (pagePort === '8001') {

    return window.location.origin;

  }

  return window.location.origin;

}



function staticUrl(path) {

  const base = getApiBase();

  return path.startsWith('/') ? `${base}${path}` : `${base}/${path}`;

}



async function parseJsonResponse(response) {

  const text = await response.text();

  if (!text || !text.trim()) {

    return { detail: `Empty response from server (HTTP ${response.status})` };

  }

  try {

    return JSON.parse(text);

  } catch {

    const snippet = text.replace(/\s+/g, ' ').slice(0, 120);

    return {

      detail: `Invalid server response (HTTP ${response.status}). Use http://127.0.0.1:8001 and run RUN_HIRING_SERVER.bat. Response: ${snippet}`,

    };

  }

}



async function postSignup(payload) {

  const API = getApiBase();

  const endpoints = [

    `${API}/api/register`,

    `${API}/signup`,

    `${API}/api/v1/agency/auth/signup`,

  ];

  let lastResponse = null;

  let lastData = { detail: 'Signup service not found. Run RUN_HIRING_SERVER.bat (port 8001)' };



  for (const url of endpoints) {

    const response = await fetch(url, {

      method: 'POST',

      headers: { 'Content-Type': 'application/json' },

      body: JSON.stringify(payload),

    });

    lastResponse = response;

    lastData = await parseJsonResponse(response);

    if (response.status !== 404) {

      return { response, data: lastData };

    }

  }

  return { response: lastResponse, data: lastData };

}



async function postLogin(payload) {

  const API = getApiBase();

  const email = (payload.email || payload.username || '').trim();

  const password = payload.password || '';



  if (!email || !password) {

    return {

      response: { ok: false, status: 400 },

      data: { detail: 'Email and password are required' },

    };

  }



  // 1) OAuth2 /token (most reliable on hiring main.py)

  const form = new URLSearchParams();

  form.append('username', email);

  form.append('password', password);

  try {

    const tokenRes = await fetch(`${API}/token`, {

      method: 'POST',

      headers: { 'Content-Type': 'application/x-www-form-urlencoded' },

      body: form,

    });

    const tokenData = await parseJsonResponse(tokenRes);

    if (tokenRes.ok && tokenData.access_token) {

      return { response: tokenRes, data: tokenData };

    }

    if (tokenRes.status !== 404) {

      return { response: tokenRes, data: tokenData };

    }

  } catch (err) {

    return {

      response: { ok: false, status: 0 },

      data: { detail: `Cannot reach server at ${API}. Run RUN_HIRING_SERVER.bat. (${err.message})` },

    };

  }



  // 2) JSON login endpoints

  const jsonEndpoints = [`${API}/api/login`, `${API}/login`, `${API}/api/v1/agency/auth/login`];

  let lastResponse = null;

  let lastData = { detail: 'Login failed' };



  for (const url of jsonEndpoints) {

    try {

      const response = await fetch(url, {

        method: 'POST',

        headers: { 'Content-Type': 'application/json' },

        body: JSON.stringify({ email, password }),

      });

      lastResponse = response;

      lastData = await parseJsonResponse(response);

      if (response.ok && lastData.access_token) {

        return { response, data: lastData };

      }

      if (response.status !== 404) {

        return { response, data: lastData };

      }

    } catch (err) {

      return {

        response: { ok: false, status: 0 },

        data: { detail: `Cannot reach server at ${API}. Run RUN_HIRING_SERVER.bat. (${err.message})` },

      };

    }

  }



  return { response: lastResponse || { ok: false, status: 0 }, data: lastData };

}


