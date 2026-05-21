/** Shared navigation — any logged-in user can access all areas. */
function renderPortalNav(activeSection) {
  const nav = document.createElement('nav');
  nav.className = 'portal-nav';
  nav.setAttribute('aria-label', 'Main navigation');
  const sections = [
    { id: 'home', label: 'Home', href: '/' },
    { id: 'jd', label: 'JD', href: '/admin' },
    { id: 'candidates', label: 'Candidates', href: '/recruiter' },
    { id: 'dashboard', label: 'Dashboard', href: '/hr' },
  ];
  let html = sections
    .map(
      (s) =>
        `<a href="${s.href}" class="${activeSection === s.id ? 'active' : ''}">${s.label}</a>`
    )
    .join('');
  html += '<span class="nav-spacer"></span>';
  html += '<a href="#" class="nav-logout" id="portal-nav-logout">Sign out</a>';
  nav.innerHTML = html;
  const wrapper = document.querySelector('.page-wrapper');
  if (wrapper) {
    wrapper.insertBefore(nav, wrapper.firstChild);
  } else {
    document.body.insertBefore(nav, document.body.firstChild);
  }
  const logout = document.getElementById('portal-nav-logout');
  if (logout) {
    logout.addEventListener('click', (e) => {
      e.preventDefault();
      localStorage.removeItem('token');
      localStorage.removeItem('username');
      document.cookie = 'access_token=; path=/; max-age=0';
      window.location.href = '/login';
    });
  }
}
