const app = {
  showLanding: () => {
    document.getElementById('landing-page').classList.remove('hidden');
    document.getElementById('admin-portal').classList.add('hidden');
    document.getElementById('recruiter-portal').classList.add('hidden');
  },

  showAdminPortal: () => {
    document.getElementById('landing-page').classList.add('hidden');
    document.getElementById('admin-portal').classList.remove('hidden');
  },

  showRecruiterPortal: () => {
    document.getElementById('landing-page').classList.add('hidden');
    document.getElementById('recruiter-portal').classList.remove('hidden');
  },

  handleTopKChange: () => {
    const select = document.getElementById('top-k-select');
    const customGroup = document.getElementById('custom-top-k-group');

    if (select.value === 'custom') {
      customGroup.style.display = 'block';
    } else {
      customGroup.style.display = 'none';
    }
  },

  init: () => {
    // Helper to fetch rankings using JD embedding
    const fetchRankings = async (jdId, topK) => {
      const resultsArea = document.getElementById('results-area');
      const tbody = document.getElementById('results-body');
      tbody.innerHTML = '<tr><td colspan="4">Loading...</td></tr>';
      resultsArea.classList.remove('hidden');

      const formData = new FormData();
      formData.append('jd_id', jdId);
      formData.append('top_k', topK);

      try {
        const res = await fetch('/match/top-by-jd', {
          method: 'POST',
          body: formData
        });
        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();

        tbody.innerHTML = '';
        if (data.matches.length === 0) {
          tbody.innerHTML = '<tr><td colspan="4">No matches found.</td></tr>';
          return;
        }

        // Store candidate IDs for email sending
        const candidateIds = [];

        data.matches.forEach(match => {
          candidateIds.push(match.resume_id);
          const scoreClass = match.ats_score >= 80 ? 'score-high' : (match.ats_score >= 50 ? 'score-medium' : 'score-low');
          const row = `
            <tr>
              <td>#${match.rank}</td>
              <td>${match.candidate_name || 'Unknown'}</td>
              <td><span class="score-badge ${scoreClass}">${match.ats_score}%</span></td>
              <td>${match.file_name}</td>
            </tr>
          `;
          tbody.innerHTML += row;
        });

        // Automatically send emails to all matched candidates
        if (candidateIds.length > 0) {
          tbody.innerHTML += '<tr><td colspan="4" style="color: blue; text-align: center; padding: 15px;">📧 Sending personalized emails to candidates...</td></tr>';

          await sendEmailsToCandidates(jdId, candidateIds);
        }

      } catch (err) {
        tbody.innerHTML = `<tr><td colspan="4" style="color: red">Error: ${err.message}</td></tr>`;
      }
    };

    // Helper to send emails to candidates
    const sendEmailsToCandidates = async (jdId, candidateIds) => {
      const tbody = document.getElementById('results-body');

      try {
        const formData = new FormData();
        formData.append('jd_id', jdId);
        candidateIds.forEach(id => formData.append('candidate_ids', id));

        const res = await fetch('/send-emails', {
          method: 'POST',
          body: formData
        });

        if (!res.ok) throw new Error(await res.text());
        const data = await res.json();

        // Update the last row with email sending results
        const lastRow = tbody.lastElementChild;
        if (lastRow) {
          lastRow.innerHTML = `<td colspan="4" style="color: green; text-align: center; padding: 15px;">
            ✅ Emails sent successfully to ${data.sent} out of ${data.total} candidates!
            ${data.failed > 0 ? `<br><span style="color: orange;">⚠️ ${data.failed} failed to send</span>` : ''}
          </td>`;
        }

      } catch (err) {
        const lastRow = tbody.lastElementChild;
        if (lastRow) {
          lastRow.innerHTML = `<td colspan="4" style="color: red; text-align: center; padding: 15px;">
            ❌ Error sending emails: ${err.message}
          </td>`;
        }
      }
    };

    // Admin: Resume Upload
    const adminForm = document.getElementById('admin-upload-form');
    if (adminForm) {
      adminForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const files = document.getElementById('resume-files').files;
        const formData = new FormData();
        for (let i = 0; i < files.length; i++) {
          formData.append('files', files[i]);
        }

        const output = document.getElementById('admin-output');
        output.innerHTML = 'Uploading...';

        try {
          const res = await fetch('/resumes/upload', {
            method: 'POST',
            headers: {
              'Authorization': 'Bearer ' + localStorage.getItem('token')
            },
            body: formData
          });
          const data = await res.json();
          output.innerHTML = `<div style="color: green">Successfully processed ${data.count} resumes.</div>`;
        } catch (err) {
          output.innerHTML = `<div style="color: red">Error: ${err.message}</div>`;
        }
      });
    }
    // Admin: Init DB
    const initBtn = document.getElementById('init-db-btn');
    if (initBtn) {
      initBtn.addEventListener('click', async () => {
        const output = document.getElementById('init-output');
        output.innerHTML = 'Initializing...';
        try {
          const res = await fetch('/init-db', { method: 'POST' });
          const data = await res.json();
          output.innerHTML = JSON.stringify(data);
        } catch (err) {
          output.innerHTML = `Error: ${err.message}`;
        }
      });
    }

    // Recruiter: JD Upload & Rank
    const jdForm = document.getElementById('jd-upload-form');
    if (jdForm) {
      jdForm.addEventListener('submit', async (e) => {
        e.preventDefault();
        const file = document.getElementById('jd-file').files[0];

        // Get topK based on selection
        const topKSelect = document.getElementById('top-k-select').value;
        let topK;

        if (topKSelect === 'all') {
          topK = 1000; // Large number to get all results
        } else {
          topK = parseInt(document.getElementById('top-k-input').value) || 5;
        }

        const formData = new FormData();
        formData.append('file', file);

        const output = document.getElementById('jd-output');
        output.innerHTML = 'Uploading and analyzing JD...';

        try {
          const res = await fetch('/jd/analyze/pdf', {
            method: 'POST',
            headers: {
              'Authorization': 'Bearer ' + localStorage.getItem('token')
            },
            body: formData
          });
          if (!res.ok) throw new Error(await res.text());
          const data = await res.json();

          const detectedRole = data.role || 'Unknown';
          output.innerHTML = `<div style="color: green">JD Analyzed! Role detected: <b>${detectedRole}</b></div>`;

          // Store the database ID for embedding-based matching
          const jdId = data.id;

          if (!jdId) {
            output.innerHTML += `<div style="color: red; margin-top: 5px;">Error: JD ID not returned from server. Please restart the backend server.</div>`;
            console.error('JD upload response:', data);
            return;
          }

          document.getElementById('jd-database-id').value = jdId;

          // Auto-fetch rankings using embedding similarity
          output.innerHTML += `<div style="color: blue; margin-top: 5px;">Auto-fetching top ${topK} matches...</div>`;
          await fetchRankings(jdId, topK);

        } catch (err) {
          output.innerHTML = `<div style="color: red">Error: ${err.message}</div>`;
        }
      });
    }
  }
};

// Initialize app
document.addEventListener('DOMContentLoaded', app.init);
