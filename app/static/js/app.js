/* ═══ Modal Helpers ═══ */
window.openModal = function(id) {
  const el = document.getElementById(id);
  if (el) el.classList.add('show');
};
window.closeModal = function(id) {
  const el = document.getElementById(id);
  if (el) el.classList.remove('show');
};

/* ═══ F11 — Dark/Light Mode ═══ */
function initTheme() {
  const saved = localStorage.getItem('theme') || 'dark';
  document.documentElement.setAttribute('data-theme', saved);
  updateToggleIcon(saved);
}
function toggleTheme() {
  const current = document.documentElement.getAttribute('data-theme') || 'dark';
  const next = current === 'dark' ? 'light' : 'dark';
  document.documentElement.setAttribute('data-theme', next);
  localStorage.setItem('theme', next);
  updateToggleIcon(next);
}
function updateToggleIcon(theme) {
  const btn = document.getElementById('theme-toggle');
  if (btn) btn.textContent = theme === 'dark' ? '☀️' : '🌙';
}
// Run immediately to prevent flash
initTheme();

/* ═══ F10 — PWA Install Prompt ═══ */
let _deferredInstallPrompt = null;
window.addEventListener('beforeinstallprompt', (e) => {
  e.preventDefault();
  _deferredInstallPrompt = e;
  const btn = document.getElementById('pwa-install-btn');
  if (btn) btn.classList.add('visible');
});
function pwaInstall() {
  if (!_deferredInstallPrompt) return;
  _deferredInstallPrompt.prompt();
  _deferredInstallPrompt.userChoice.then(() => {
    _deferredInstallPrompt = null;
    const btn = document.getElementById('pwa-install-btn');
    if (btn) btn.classList.remove('visible');
  });
}

const API = '';  // Same origin

// ─── Auth Helpers ───
function getUser() {
  const u = localStorage.getItem('user');
  return u ? JSON.parse(u) : null;
}

function setAuth(user) {
  localStorage.setItem('user', JSON.stringify(user));
}

function clearAuth() {
  localStorage.removeItem('user');
}

function requireAuth() {
  if (!getUser()) {
    window.location.href = '/login';
    return false;
  }
  return true;
}

// ─── API Fetch Helper ───
async function apiFetch(url, options = {}) {
  const timeout = options.timeout || 15000; // Default 15s
  const controller = new AbortController();
  const timeoutId = setTimeout(() => controller.abort(), timeout);

  try {
    const token = 
      localStorage.getItem('token') ||
      localStorage.getItem('access_token');
    
    const headers = {
      'Content-Type': 'application/json'
    };
    
    // Only add auth if token exists and is valid
    if (token && token !== 'null' && 
        token !== 'undefined') {
      headers['Authorization'] = `Bearer ${token}`;
    }
    
    // Merge caller headers
    if (options.headers) {
      Object.assign(headers, options.headers);
    }
    
    // Make sure body is always a string
    let body = options.body;
    if (body && typeof body !== 'string') {
      body = JSON.stringify(body);
    }
    
    const fetchOptions = {
      method: options.method || 'GET',
      headers: headers,
      signal: controller.signal
    };
    
    if (body) {
      fetchOptions.body = body;
    }
    
    console.log(
      `[apiFetch] ${fetchOptions.method} ${url}`
    );
    if (body) {
      console.log('[apiFetch] body:', body);
    }
    
    const response = await fetch(url, fetchOptions);
    clearTimeout(timeoutId);
    
    console.log(
      `[apiFetch] status: ${response.status}`
    );
    
    // Handle non-JSON responses
    const contentType = response.headers.get(
      'content-type'
    );
    if (!contentType || 
        !contentType.includes('application/json')) {
      const text = await response.text();
      console.error(
        '[apiFetch] Non-JSON response:', text
      );
      return { 
        error: `Server error: ${response.status}` 
      };
    }
    
    const data = await response.json();
    
    // Handle 401 unauthorized
    if (response.status === 401) {
      console.warn('[apiFetch] 401 - redirecting');
      localStorage.removeItem('token');
      localStorage.removeItem('access_token');
      localStorage.removeItem('user');
      window.location.href = '/login';
      return null;
    }
    
    return data;
    
  } catch(e) {
    clearTimeout(timeoutId);
    if (e.name === 'AbortError') {
      console.error('[apiFetch] ERROR: Request timed out');
      return { 
        error: `Request timed out after ${timeout/1000}s. Please check your connection.` 
      };
    }
    console.error('[apiFetch] EXCEPTION:', e);
    console.error('[apiFetch] URL was:', url);
    // Return error object instead of throwing
    return { 
      error: 'Network error: ' + e.message 
    };
  }
}

// ─── Toast Notification (Fixed stacking at bottom-right) ───
function showToast(message, type = 'info') {
  let container = document.querySelector('.toast-stack-container');
  if (!container) {
    container = document.createElement('div');
    container.className = 'toast-stack-container';
    document.body.appendChild(container);
  }

  const toast = document.createElement('div');
  toast.className = `toast-item toast-${type}`;
  
  // Icon based on type
  let icon = '🔔';
  if (type === 'success') icon = '✅';
  if (type === 'error') icon = '❌';
  if (type === 'warning') icon = '⚠️';

  toast.innerHTML = `
    <span class="toast-icon">${icon}</span>
    <span class="toast-message">${message}</span>
    <button class="toast-close" onclick="this.parentElement.remove()">&times;</button>
  `;

  container.appendChild(toast);

  // Auto-dismiss after 4 seconds
  setTimeout(() => {
    toast.classList.add('fade-out');
    setTimeout(() => toast.remove(), 400);
  }, 4000);
}

// ─── Real-time Notification Management ───
async function updateNotificationBadges() {
  const user = getUser();
  if (!user) return;
  
  try {
    const data = await apiFetch('/api/notifications/unread-count');
    if (data && typeof data.count !== 'undefined') {
      const count = data.count;
      const displayCount = count > 99 ? '99+' : count;

      // Update Sidebar Badge
      const sidebarBadge = document.getElementById('sidebarNotifBadge');
      if (sidebarBadge) {
        sidebarBadge.textContent = displayCount;
        sidebarBadge.style.display = count > 0 ? 'inline-flex' : 'none';
      }

      // Update Dashboard Stat Card
      const dashboardStat = document.getElementById('stat-notifications');
      if (dashboardStat) {
        dashboardStat.textContent = count;
      }

      // Update Navbar Bell Badge if exists
      const navBadge = document.querySelector('.notification-bell .badge');
      if (navBadge) {
        navBadge.textContent = displayCount;
        if (count > 0) navBadge.classList.add('show');
        else navBadge.classList.remove('show');
      }
    }
  } catch (e) {
    console.error('[Notification Update Failed]', e);
  }
}
// ─── Sidebar Active State ───
function setActiveNav() {
  const path = window.location.pathname;
  document.querySelectorAll('.nav-item').forEach(item => {
    item.classList.remove('active');
    if (item.getAttribute('href') === path) {
      item.classList.add('active');
    }
  });
}

// ─── User Info in Sidebar ───
function renderUserInfo() {
  const user = getUser();
  if (!user) return;

  const nameEl = document.querySelector('.user-name');
  const roleEl = document.querySelector('.user-role');
  const avatarEl = document.querySelector('.user-avatar');

  if (nameEl) nameEl.textContent = user.name;
  if (roleEl) roleEl.textContent = user.role;
  if (avatarEl) avatarEl.textContent = user.name ? user.name[0].toUpperCase() : '?';
}

// ─── Mobile Menu ───
function toggleSidebar() {
  const sidebar = document.querySelector('.sidebar');
  if (sidebar) {
    sidebar.classList.toggle('open');
    document.body.classList.toggle('sidebar-open');
  }
}

// Close sidebar on outside click or when selecting a nav item (mobile)
document.addEventListener('click', (e) => {
  const sidebar = document.querySelector('.sidebar');
  const menuBtn = document.querySelector('.menu-toggle');
  
  if (sidebar && sidebar.classList.contains('open')) {
    // If click is outside sidebar and NOT on the menu button
    if (!sidebar.contains(e.target) && !menuBtn?.contains(e.target)) {
      toggleSidebar();
    }
  }
});


// ─── Utilities ───
function escapeHtml(text) {
  if (!text) return '';
  const d = document.createElement('div');
  d.textContent = text;
  return d.innerHTML;
}

function timeAgo(dateStr) {
  if (!dateStr) return '';
  const date = new Date(dateStr);
  const now = new Date();
  const diff = Math.floor((now - date) / 1000);

  if (diff < 60) return 'Just now';
  if (diff < 3600) return `${Math.floor(diff / 60)}m ago`;
  if (diff < 86400) return `${Math.floor(diff / 3600)}h ago`;
  if (diff < 604800) return `${Math.floor(diff / 86400)}d ago`;
  return date.toLocaleDateString();
}

function formatDate(dateStr) {
  if (!dateStr) return '';
  return new Date(dateStr).toLocaleDateString('en-US', {
    year: 'numeric', month: 'short', day: 'numeric',
  });
}

/**
 * renderMedia - Detects media type from URL and returns appropriate HTML (img, video, iframe).
 */
function renderMedia(url, className = '', style = '') {
  if (!url) return '';
  
  const trimmedUrl = String(url).trim();
  if (trimmedUrl === 'null' || trimmedUrl === 'undefined' || !trimmedUrl) return '';
  
  // YouTube
  const ytMatch = trimmedUrl.match(/(?:https?:\/\/)?(?:www\.)?(?:youtube\.com\/watch\?v=|youtu\.be\/|youtube\.com\/embed\/)([a-zA-Z0-9_-]{11})/);
  if (ytMatch) {
    return `<iframe class="${className}" style="${style}; aspect-ratio: 16/9; border: none; width: 100%; border-radius: 12px;" src="https://www.youtube.com/embed/${ytMatch[1]}" allowfullscreen></iframe>`;
  }
  
  // Vimeo
  const vimeoMatch = trimmedUrl.match(/(?:https?:\/\/)?(?:www\.)?vimeo\.com\/(\d+)/);
  if (vimeoMatch) {
    return `<iframe class="${className}" style="${style}; aspect-ratio: 16/9; border: none; width: 100%; border-radius: 12px;" src="https://player.vimeo.com/video/${vimeoMatch[1]}" allowfullscreen></iframe>`;
  }
  
  // Direct Video
  if (trimmedUrl.match(/\.(mp4|webm|ogg|mov)(\?.*)?$/i)) {
    return `<video class="${className}" style="${style}; width: 100%; border-radius: 12px;" src="${trimmedUrl}" controls playsinline></video>`;
  }
  
  // Default: Image
  return `<img class="${className}" style="${style}; width: 100%; border-radius: 12px;" src="${trimmedUrl}" alt="Media" onerror="this.src='/static/images/placeholder.png'; this.onerror=null;">`;
}

// ─── Clipboard Helpers ───
function copyToClipboard(text, msg = 'Link copied to clipboard!') {
  navigator.clipboard.writeText(text).then(() => {
    showToast(msg, 'success');
  }).catch(() => {
    showToast('Failed to copy', 'error');
  });
}

function copyPageLink(path, msg) {
  const url = window.location.origin + path;
  copyToClipboard(url, msg);
}

// ─── Logout ───
async function logout() {
  try {
    await apiFetch('/api/auth/logout', { method: 'POST' });
  } catch (e) {
    console.error('Logout API failed', e);
  }
  clearAuth();
  window.location.href = '/login';
}

// ─── Init ───
document.addEventListener('DOMContentLoaded', () => {
  setActiveNav();
  renderUserInfo();

  // Global Parallax Cursor Effect
  const spaceBg = document.getElementById('spaceBg');
  const particles = document.getElementById('particlesOverlay');
  
  if (spaceBg && particles) {
    document.addEventListener('mousemove', (e) => {
      const w = window.innerWidth;
      const h = window.innerHeight;
      
      // Calculate cursor position relative to center (-1 to 1)
      const x = (e.clientX - w/2) / (w/2);
      const y = (e.clientY - h/2) / (h/2);
      
      // Apply transforms
      requestAnimationFrame(() => {
        spaceBg.style.transform = `translate(${x * -20}px, ${y * -20}px)`;
        particles.style.transform = `translate(${x * -40}px, ${y * -40}px)`;
      });
    });
  }

  // ─── Global Card Menu Helpers ───
  window.toggleCardMenu = function(id, e) {
    if (e) {
      e.stopPropagation();
      e.preventDefault();
    }
    const menu = document.getElementById(`menu-${id}`);
    if (!menu) return;

    const wasOpen = menu.classList.contains('show');
    closeAllMenus();
    if (!wasOpen) menu.classList.add('show');
  };

  window.closeAllMenus = function() {
    document.querySelectorAll('.menu-dropdown').forEach(m => m.classList.remove('show'));
  };

  document.addEventListener('click', (e) => {
    if (!e.target.closest('.card-menu-container')) {
      closeAllMenus();
    }
  });

  // Initial and periodic update
  updateNotificationBadges();
  setInterval(updateNotificationBadges, 10000); // 10s poll
});
