/**
 * EDU LINK HUB - Opportunities JavaScript
 * Redesign & Enhanced Logic - Fresh Implementation
 */

console.log('🚀 opportunities.js loading...');

const SOURCE_ICONS = {
    'adzuna': '🔍',
    'remotive': '🌐',
    'themuse': '🎨',
    'jobicy': '💼',
    'devpost': '💻',
    'mlh': '⚡',
    'eventbrite': '🎟️',
    'internshala': '🎓',
    'unstop': '🏆'
};

function getSourceIcon(source) {
    return SOURCE_ICONS[(source || '').toLowerCase()] || '💼';
}

const TYPE_GRADIENTS = {
    'job': 'var(--grad-job)',
    'hackathon': 'var(--grad-hackathon)',
    'event': 'var(--grad-event)',
    'remote': 'var(--grad-remote)',
    'internship': 'var(--grad-internship)'
};

function generateCardBanner(opp) {
    const type = (opp.opportunity_type || opp.category || 'job').toLowerCase();
    const isRemote = (opp.location || '').toLowerCase().includes('remote');
    if (isRemote) return TYPE_GRADIENTS['remote'];
    return TYPE_GRADIENTS[type] || TYPE_GRADIENTS['job'];
}

function generateLetterAvatar(name) {
    if (!name) return '?';
    return name.charAt(0).toUpperCase();
}

function renderCard(opp) {
    const bannerGrad = generateCardBanner(opp);
    const letter = generateLetterAvatar(opp.company);
    const hasLiked = opp.has_liked ? 'active' : '';
    const bannerContent = opp.image ? 
        `<img src="${opp.image}" alt="${opp.company}" onerror="this.style.display='none'; this.nextElementSibling.style.display='flex';">` : 
        '';
    const avatarStyle = opp.image ? 'style="display:none;"' : '';

    return `
        <div class="opp-card opportunity-card" data-id="${opp._id}" data-opp-id="${opp._id}">
            <div class="card-banner" style="background: ${bannerGrad}">
                ${bannerContent}
                <div class="letter-avatar" ${avatarStyle}>${letter}</div>
                
                <div style="position:absolute;top:10px;right:10px;
                            display:flex;align-items:center;gap:6px;z-index:50;">
                  
                  <!-- Source badge -->
                  <span style="background:rgba(0,0,0,0.5);color:#aaa;
                               font-size:11px;padding:3px 8px;border-radius:20px;
                               display:flex;align-items:center;gap:4px;">
                    ${getSourceIcon(opp.source)} via ${opp.source || 'unknown'}
                  </span>

                  <!-- THREE DOT BUTTON — inline onclick, no external listener needed -->
                  <button 
                    onclick="handleThreeDot(event, this)"
                    data-id="${opp._id}"
                    data-source="${opp.source || ''}"
                    title="More options"
                    style="background:rgba(255,255,255,0.12);
                           border:1px solid rgba(255,255,255,0.25);
                           color:#fff;
                           width:28px;height:28px;
                           border-radius:50%;
                           cursor:pointer;
                           font-size:18px;
                           font-weight:bold;
                           display:flex;align-items:center;justify-content:center;
                           line-height:1;
                           flex-shrink:0;
                           z-index:50;
                           position:relative;
                           padding:0;">&#8942;</button>
                </div>

                <div class="type-badge">${(opp.opportunity_type || opp.category || 'Job').toUpperCase()}</div>
                <div class="location-badge">📍 ${opp.location || 'Remote'}</div>
            </div>
            <div class="opp-card-body">
                <div class="company-name">${opp.company}</div>
                <h2 class="opp-title" title="${opp.role}">${opp.role}</h2>
                <div class="opp-meta-row">
                    <div class="opp-meta-item">🗓️ ${opp.deadline || 'N/A'}</div>
                    <div class="opp-meta-item">🎓 ${opp.eligibility || 'Any'}</div>
                </div>
                <div class="tag-pills">
                    ${(opp.tags || []).map(tag => `<span class="tag-pill">#${tag}</span>`).join('')}
                </div>
                <p class="opp-desc">${opp.description || 'No description provided.'}</p>
                
                <div class="opp-action-row">
                    <div class="action-likes ${hasLiked}" onclick="reactToOpportunity('${opp._id}', this)">
                        <span class="emoji">👍</span> 
                        <span class="count" id="count-${opp._id}">${opp.total_reactions || 0}</span>
                        <span>LIKES</span>
                    </div>
                    <div class="action-buttons">
                        <a href="/opportunities/${opp._id}" class="btn-opp btn-details">View Details</a>
                        <a href="${opp.apply_link || '#'}" target="_blank" class="btn-opp btn-apply">Apply Now →</a>
                        <a href="javascript:void(0)" onclick="discussInChat('${opp._id}', '${opp.role.replace(/'/g, "\\'")}')" class="btn-opp btn-discuss">💬</a>
                    </div>
                </div>
            </div>
        </div>
    `;
}

// ═══════════════════════════════════════════
// THREE DOT MENU — clean implementation
// ═══════════════════════════════════════════

window.handleThreeDot = function(event, btn) {
  event.stopPropagation();
  event.preventDefault();

  console.log('✅ handleThreeDot triggered for:', btn.dataset.id);

  // Remove any existing dropdown
  const existing = document.getElementById('opp-ctx-menu');
  if (existing) {
    const wasSame = existing.dataset.forId === btn.dataset.id;
    existing.remove();
    if (wasSame) return; // toggle off
  }

  const oppId  = btn.dataset.id;
  
  // Safe isAdmin detection (avoiding optional chaining for older browsers just in case)
  const metaAdmin = document.querySelector('meta[name="is-admin"]');
  const isAdmin = (
    document.body.getAttribute('data-is-admin') === 'true' ||
    document.body.dataset.isAdmin === 'true' ||
    (metaAdmin && metaAdmin.getAttribute('content') === 'true')
  );

  console.log('🔑 isAdmin:', isAdmin);

  // Build menu
  const menu = document.createElement('div');
  menu.id = 'opp-ctx-menu';
  menu.dataset.forId = oppId;
  menu.innerHTML = `
    <div onclick="oppAction('bookmark','${oppId}')">
      <span>🔖</span> Bookmark
    </div>
    <div onclick="oppAction('share','${oppId}')">
      <span>🔗</span> Share Link
    </div>
    ${isAdmin ? `
    <div onclick="oppAction('edit','${oppId}')">
      <span>✏️</span> Edit
    </div>
    <div onclick="oppAction('delete','${oppId}')" 
         style="color:#ff4757;">
      <span>🗑️</span> Delete
    </div>` : ''}
    <div onclick="oppAction('report','${oppId}')" 
         style="color:#ffa502;">
      <span>🚩</span> Report
    </div>
  `;
  document.body.appendChild(menu);

  // Apply ALL styles inline — zero CSS file dependency
  const r = btn.getBoundingClientRect();
  Object.assign(menu.style, {
    position: 'fixed',
    top: (r.bottom + 6) + 'px',
    left: (r.right - 175) + 'px',
    minWidth: '175px',
    background: '#1a1a2e',
    border: '1px solid rgba(108,99,255,0.5)',
    borderRadius: '12px',
    boxShadow: '0 20px 60px rgba(0,0,0,0.95)',
    overflow: 'hidden',
    fontFamily: 'sans-serif',
    fontSize: '14px',
    zIndex: '2147483647'
  });

  // Style each item inline too
  menu.querySelectorAll('div').forEach(div => {
    Object.assign(div.style, {
      padding: '11px 16px',
      cursor: 'pointer',
      display: 'flex',
      alignItems: 'center',
      gap: '10px',
      color: div.style.color || '#cccccc',
      borderBottom: '1px solid rgba(255,255,255,0.05)',
      transition: 'background 0.15s'
    });
    div.addEventListener('mouseenter', () => {
      div.style.background = 'rgba(108,99,255,0.2)';
      if (!div.style.color || div.style.color === 'rgb(204, 204, 204)')
        div.style.color = '#ffffff';
    });
    div.addEventListener('mouseleave', () => {
      div.style.background = 'transparent';
    });
  });

  // Edge corrections
  requestAnimationFrame(() => {
    const m = menu.getBoundingClientRect();
    if (m.bottom > window.innerHeight - 8)
      menu.style.top = (r.top - m.height - 6) + 'px';
    if (m.left < 8)
      menu.style.left = '8px';
    if (m.right > window.innerWidth - 8)
      menu.style.left = (window.innerWidth - m.width - 8) + 'px';
  });

  console.log('✅ Menu appended to body');
};

// Close menu on outside click
document.addEventListener('click', function(e) {
  const menu = document.getElementById('opp-ctx-menu');
  if (menu && !menu.contains(e.target)) {
    menu.remove();
  }
});

// Close on scroll
window.addEventListener('scroll', function() {
  const menu = document.getElementById('opp-ctx-menu');
  if (menu) menu.remove();
}, { passive: true });

// ── Action handler ───────────────────────────────────
window.oppAction = function(action, id) {
  const menu = document.getElementById('opp-ctx-menu');
  if (menu) menu.remove();

  if (action === 'bookmark') {
    fetch('/api/bookmarks/', {
      method: 'POST',
      headers: {'Content-Type':'application/json'},
      body: JSON.stringify({contentId: id, contentType: 'opportunity'})
    })
    .then(r => r.json())
    .then(d => showOppToast(d.message || 'Bookmarked!'))
    .catch(() => showOppToast('Error bookmarking'));
  }

  if (action === 'share') {
    const url = window.location.origin + '/opportunities/' + id;
    
    // Modern Web Share API (Mobile native sharing)
    if (navigator.share) {
      navigator.share({
        title: 'EDU Link Hub: Opportunity',
        url: url
      })
      .then(() => showOppToast('🔗 Shared successfully!'))
      .catch((err) => {
        if (err.name !== 'AbortError') {
           copyToClipboardFallback(url);
        }
      });
    } else {
      copyToClipboardFallback(url);
    }
    
    function copyToClipboardFallback(text) {
      if (navigator.clipboard) {
        navigator.clipboard.writeText(text)
          .then(() => showOppToast('🔗 Link copied!'))
          .catch(() => copyTextOldWay(text));
      } else {
        copyTextOldWay(text);
      }
    }
    
    function copyTextOldWay(text) {
      const tempInput = document.createElement('input');
      tempInput.value = text;
      document.body.appendChild(tempInput);
      tempInput.select();
      try {
        document.execCommand('copy');
        showOppToast('🔗 Link copied!');
      } catch (err) {
        showOppToast('URL: ' + text);
      }
      document.body.removeChild(tempInput);
    }
  }

  if (action === 'edit') {
    window.location.href = '/opportunities/' + id + '/edit';
  }

  if (action === 'delete') {
    if (!confirm('Delete this opportunity?')) return;
    fetch('/api/opportunities/' + id, {method:'DELETE'})
      .then(r => r.json())
      .then(d => {
        showOppToast(d.message || 'Deleted');
        document.querySelector(`.opportunity-card[data-id="${id}"]`)?.remove();
      })
      .catch(() => showOppToast('Error deleting'));
  }

  if (action === 'report') {
    if (window.handleReport) {
        window.handleReport(id, 'opportunity');
    } else {
        fetch('/api/opportunities/' + id + '/report', {method:'POST'})
          .then(r => r.json())
          .then(d => showOppToast(d.message || 'Reported'))
          .catch(() => showOppToast('Error reporting'));
    }
  }
};

// ── Toast ────────────────────────────────────────────
window.showOppToast = function(msg) {
  document.querySelectorAll('.opp-toast').forEach(t => t.remove());
  const t = document.createElement('div');
  t.className = 'opp-toast';
  t.textContent = msg;
  document.body.appendChild(t);
  setTimeout(() => t.remove(), 3000);
};

// --- Supporting Functions ---
window.reactToOpportunity = async function(oppId, btn) {
    const countSpan = document.getElementById(`count-${oppId}`);
    if (!countSpan) return;
    let currentCount = parseInt(countSpan.innerText) || 0;
    const isActive = btn.classList.contains('active');
    
    // Optimistic
    btn.classList.toggle('active');
    countSpan.innerText = isActive ? Math.max(0, currentCount - 1) : currentCount + 1;

    try {
        const res = await fetch(`/api/opportunities/${oppId}/react`, { 
            method: 'POST',
            headers: {'Content-Type': 'application/json'}
        });
        const d = await res.json();
        if (d && d.total_reactions !== undefined) {
            countSpan.innerText = d.total_reactions;
        }
    } catch (err) {
        console.error(err);
        // Rollback
        btn.classList.toggle('active');
        countSpan.innerText = currentCount;
    }
};

window.discussInChat = function(oppId, oppTitle) {
    const encoded = encodeURIComponent('Discussing: ' + oppTitle + ' - ');
    window.location.href = `/community/channel/career-internships?prefill=${encoded}&opp_id=${oppId}`;
};

window.showSkeletons = function(containerId, count = 6) {
    const container = document.getElementById(containerId);
    if (!container) return;
    let html = '';
    for (let i = 0; i < count; i++) {
        html += `
            <div class="skeleton-card skeleton">
                <div class="skeleton-banner"></div>
                <div class="skeleton-body">
                    <div class="skeleton-text skeleton-title"></div>
                    <div class="skeleton-text skeleton-line"></div>
                    <div class="skeleton-text skeleton-line"></div>
                    <div class="skeleton-text skeleton-line half"></div>
                </div>
            </div>
        `;
    }
    container.innerHTML = html;
};

// ══════════════════════════════════════════════════════
// CREATE OPPORTUNITY MODAL
// ══════════════════════════════════════════════════════

window.openCreateOppModal = function() {
  const modal = document.getElementById('createOppModal');
  if (!modal) return;
  modal.style.display = 'flex';
  document.body.style.overflow = 'hidden';
};

window.closeCreateOppModal = function() {
  const modal = document.getElementById('createOppModal');
  if (!modal) return;
  modal.style.display = 'none';
  document.body.style.overflow = '';
};

// Close on backdrop click
document.addEventListener('click', function(e) {
  const modal = document.getElementById('createOppModal');
  if (modal && e.target === modal) closeCreateOppModal();
});

// Close on Escape
document.addEventListener('keydown', function(e) {
  if (e.key === 'Escape') closeCreateOppModal();
});

window.submitCreateOpp = async function(e) {
  e.preventDefault();
  const form = document.getElementById('createOppForm');
  const btn  = document.getElementById('btnSubmitOpp');
  if (!form || !btn) return;

  // Validate required selects
  const category = form.querySelector('[name="category"]').value;
  if (!category) { showOppToast('⚠️ Please select a category'); return; }

  btn.textContent = '⏳ Submitting...';
  btn.disabled = true;

  try {
    const formData = new FormData(form);

    // Get auth token from localStorage (matches your apiFetch setup)
    const token = localStorage.getItem('access_token') || localStorage.getItem('token') || '';

    const res = await fetch('/api/opportunities/', {
      method: 'POST',
      headers: token ? { 'Authorization': 'Bearer ' + token } : {},
      body: formData
    });

    const data = await res.json();

    if (res.ok) {
      showOppToast('✅ Opportunity submitted! Pending review.');
      form.reset();
      document.getElementById('oppImageLabel').textContent = 'Click to upload image';
      closeCreateOppModal();

      // If admin/moderator — auto-approved so refresh feed
      if (currentUserRole === 'admin' || currentUserRole === 'moderator') {
        setTimeout(() => location.reload(), 1200);
      }
    } else {
      showOppToast('❌ ' + (data.error || 'Failed to submit. Try again.'));
    }
  } catch (err) {
    console.error(err);
    showOppToast('❌ Network error. Please try again.');
  } finally {
    btn.textContent = '🚀 Submit Opportunity';
    btn.disabled = false;
  }
};

console.log('✅ opportunities.js loaded successfully');

