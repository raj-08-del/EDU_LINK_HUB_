/**
 * EDU LINK HUB - College Directory JavaScript
 * Redesign & Enhanced Logic
 */

let currentPage = 1;
let currentType = 'all';
let allColleges = []; // For client-side filtering if needed

/**
 * Renders a single college card.
 */
function renderCollegeCard(c) {
    const type = (c.type || 'default').toLowerCase();
    const bannerClass = `banner-${type}`;
    const badgeClass = `badge-${type}`;
    const letter = c.name ? c.name.charAt(0).toUpperCase() : '?';
    
    // Generate a consistent color based on name
    const colors = ['#6c63ff', '#00d4ff', '#4ecca3', '#ff2a6d', '#ff9f43'];
    const colorIndex = c.name ? c.name.length % colors.length : 0;
    const accentColor = colors[colorIndex];

    return `
        <div class="college-card" onclick="window.location.href='/colleges/${c._id}'">
            <div class="card-banner ${bannerClass}">
                <div class="letter-avatar" style="color: ${accentColor}; border-color: ${accentColor}44;">
                    ${letter}
                </div>
            </div>
            <div class="card-body">
                <h3 class="college-name">
                    ${c.name}
                    ${c.is_verified ? '<span class="verified-badge">✅</span>' : ''}
                </h3>
                <div class="college-location">📍 ${c.city}, ${c.state || ''}</div>
                
                <div class="card-divider"></div>
                
                <div class="card-info-row">
                    <span class="type-badge ${badgeClass}">${c.type}</span>
                    <span class="est-year">Est. ${c.established || 'N/A'}</span>
                </div>
                
                <div class="card-actions">
                    <a href="javascript:void(0)" class="btn-join" onclick="event.stopPropagation(); joinEcosystem('${c._id}')">JOIN ECOSYSTEM</a>
                    <a href="/colleges/${c._id}" class="btn-explore">EXPLORE HUB →</a>
                </div>
            </div>
        </div>
    `;
}

/**
 * Fetches and displays directory stats.
 */
async function fetchDirectoryStats() {
    try {
        const stats = await apiFetch('/api/colleges/stats');
        if (stats && !stats.error) {
            const statsBar = document.getElementById('directoryStats');
            if (statsBar) {
                statsBar.innerHTML = `
                    <span class="stat-pill"><b>${stats.total || 0}</b> Colleges</span>
                    <span class="stat-pill"><b>${stats.cities || 0}</b> Cities</span>
                    <span class="stat-pill"><b>${stats.states || 0}</b> States</span>
                `;
            }
        }
    } catch (e) {
        console.error('Stats fetch failed', e);
    }
}

/**
 * Loads colleges from the server.
 */
async function loadColleges(append = false) {
    const grid = document.getElementById('collegesGrid');
    const loadMoreBtn = document.getElementById('loadMoreBtn');
    const emptyState = document.getElementById('emptyState');

    if (!append) {
        grid.innerHTML = '<div class="skeleton-card"></div>'.repeat(3);
        emptyState.style.display = 'none';
        currentPage = 1;
    }

    const url = `/api/colleges/?type=${currentType}&page=${currentPage}&limit=12`;
    
    try {
        const res = await apiFetch(url);
        if (!res || res.error) throw new Error(res?.error || 'Load failed');

        if (!append) {
            grid.innerHTML = '';
            allColleges = res.colleges;
        } else {
            allColleges = [...allColleges, ...res.colleges];
        }

        if (allColleges.length === 0) {
            emptyState.style.display = 'block';
            loadMoreBtn.style.display = 'none';
        } else {
            res.colleges.forEach(c => {
                grid.innerHTML += renderCollegeCard(c);
            });
            loadMoreBtn.style.display = (currentPage < res.total_pages) ? 'block' : 'none';
        }
    } catch (e) {
        console.error(e);
        showToast('Failed to load colleges', 'error');
    }
}

function loadMore() {
    currentPage++;
    loadColleges(true);
}

/**
 * Live Search Filter (Client-side).
 */
let searchTimeout;
function initSearch() {
    const searchInput = document.getElementById('collegeSearch');
    if (!searchInput) return;

    searchInput.addEventListener('input', (e) => {
        clearTimeout(searchTimeout);
        searchTimeout = setTimeout(() => {
            const query = e.target.value.toLowerCase().trim();
            filterColleges(query);
        }, 300);
    });
}

function filterColleges(query) {
    const grid = document.getElementById('collegesGrid');
    const cards = grid.querySelectorAll('.college-card');
    let visibleCount = 0;

    cards.forEach(card => {
        const name = card.querySelector('.college-name').textContent.toLowerCase();
        const location = card.querySelector('.college-location').textContent.toLowerCase();
        
        if (name.includes(query) || location.includes(query)) {
            card.style.display = 'flex';
            visibleCount++;
        } else {
            card.style.display = 'none';
        }
    });

    document.getElementById('emptyState').style.display = visibleCount === 0 ? 'block' : 'none';
}

/**
 * Filter Tabs Logic.
 */
function initFilters() {
    const pills = document.querySelectorAll('.filter-pill');
    pills.forEach(pill => {
        pill.addEventListener('click', () => {
            pills.forEach(p => p.classList.remove('active'));
            pill.classList.add('active');
            currentType = pill.dataset.type;
            loadColleges();
        });
    });
}

/**
 * Join Ecosystem Placeholder.
 */
function joinEcosystem(collegeId) {
    showToast('Request sent to join college ecosystem! ✅', 'success');
}

// Initialization
document.addEventListener('DOMContentLoaded', () => {
    fetchDirectoryStats();
    loadColleges();
    initSearch();
    initFilters();
});

// Modal Logic (Preserved)
function openModal(id) {
    document.getElementById(id).style.display = 'flex';
}
function closeModal(id) {
    document.getElementById(id).style.display = 'none';
}

async function saveCollege(e) {
    e.preventDefault();
    const payload = {
        name: document.getElementById('cc-name').value.trim(),
        short_name: document.getElementById('cc-short').value.trim(),
        city: document.getElementById('cc-city').value.trim(),
        state: document.getElementById('cc-state').value.trim(),
        type: document.getElementById('cc-type').value,
        established: parseInt(document.getElementById('cc-year').value) || null,
        website: document.getElementById('cc-website').value.trim(),
        description: document.getElementById('cc-desc').value.trim()
    };

    try {
        const res = await apiFetch('/api/colleges/', { method: 'POST', body: payload });
        if (res && !res.error) {
            showToast('College created!', 'success');
            closeModal('createCollegeModal');
            loadColleges();
        } else {
            showToast(res?.error || 'Failed to create', 'error');
        }
    } catch (e) {
        showToast('Server error', 'error');
    }
}
