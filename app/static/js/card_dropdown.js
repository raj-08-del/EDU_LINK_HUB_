/**
 * Global Card Dropdown Handler
 * Handles all ⋮ menu interactions across the platform using event delegation.
 */

document.addEventListener('DOMContentLoaded', () => {
    // ─── Global Event Delegation for Menu Triggers ───
    document.addEventListener('click', (e) => {
        // 1. Toggle Dropdown on ⋮ Button Click
        const trigger = e.target.closest('.card-dropdown-trigger');
        if (trigger) {
            e.stopPropagation();
            e.preventDefault();
            const id = trigger.dataset.id;
            toggleDropdown(id, trigger);
            return;
        }

        // 2. Handle Action Item Click
        const menuItem = e.target.closest('[data-action]');
        if (menuItem) {
            e.stopPropagation();
            e.preventDefault();
            const action = menuItem.dataset.action;
            const id = menuItem.dataset.id;
            const type = menuItem.dataset.type;
            handleMenuAction(action, id, type, menuItem);
            closeAllDropdowns();
            return;
        }

        // 3. Clear all on outside click
        if (!e.target.closest('.card-dropdown-container') && !e.target.closest('.card-menu-container')) {
            closeAllDropdowns();
            // Also call global closer if it exists (from app.js legacy)
            if (window.closeAllMenus) window.closeAllMenus();
        }
    });

    function toggleDropdown(id, trigger) {
        const dropdown = document.querySelector(`.card-dropdown-menu[data-id="${id}"]`);
        if (!dropdown) return;

        const isVisible = dropdown.classList.contains('show');
        closeAllDropdowns();

        if (!isVisible) {
            dropdown.classList.add('show');
            ensureVisibility(dropdown, trigger);
        }
    }

    function closeAllDropdowns() {
        document.querySelectorAll('.card-dropdown-menu.show').forEach(m => m.classList.remove('show'));
    }

    /**
     * Mobile-friendly positioning check
     * Ensures the dropdown doesn't overflow the left/right/bottom of the viewport.
     */
    function ensureVisibility(dropdown, trigger) {
        const rect = dropdown.getBoundingClientRect();
        const viewportWidth = window.innerWidth;
        const viewportHeight = window.innerHeight;

        // Reset positions
        dropdown.style.right = '0';
        dropdown.style.left = 'auto';
        dropdown.style.top = '40px';
        dropdown.style.bottom = 'auto';

        // Check horizontal overflow
        if (rect.right > viewportWidth - 20) {
            dropdown.style.right = '0';
            dropdown.style.left = 'auto';
        }
        if (rect.left < 20) {
            dropdown.style.left = '0';
            dropdown.style.right = 'auto';
        }

        // Check vertical overflow (if menu is near bottom of screen)
        if (rect.bottom > viewportHeight - 20) {
            dropdown.style.top = 'auto';
            dropdown.style.bottom = '40px';
        }
    }

    async function handleMenuAction(action, id, type, element) {
        switch (action) {
            case 'bookmark':
                await handleBookmark(id, type, element);
                break;
            case 'delete':
                await handleDelete(id, type, element);
                break;
            case 'copy':
                handleCopy(id, type, element);
                break;
            case 'report':
                handleReport(id, type);
                break;
            case 'edit':
                handleEdit(id, type);
                break;
            case 'hide':
                await handleHide(id, type, element);
                break;
        }
    }

    // ─── Action Implementations ───

    async function handleBookmark(id, type, element) {
        try {
            const isBookmarked = element.innerText.toLowerCase().includes('remove');
            const method = isBookmarked ? 'DELETE' : 'POST';
            // Use specific pattern requested: /api/bookmarks/<type>/<id>
            const url = `/api/bookmarks/${type}/${id}`;
            
            const response = await apiFetch(url, { method });
            
            // Toggle visual state
            if (isBookmarked) {
                element.innerHTML = `<span>🔖</span> Bookmark ${capitalize(type)}`;
                showToast('Removed from bookmarks', 'info');
                // If we are on the Saved Items page, remove the card
                if (window.location.pathname === '/bookmarks') {
                    smoothRemoveCard(element);
                }
            } else {
                element.innerHTML = `<span>🔖</span> Remove Bookmark`;
                showToast('Bookmarked successfully!', 'success');
            }
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    async function handleDelete(id, type, element) {
        const confirmMsg = type === 'bookmark' 
            ? 'Remove this item from your saved list?' 
            : `CRITICAL: Are you sure you want to PERMANENTLY DELETE this ${type}? This cannot be undone.`;
            
        if (!confirm(confirmMsg)) return;
        
        try {
            let url = '';
            if (type === 'event') url = `/api/events/${id}`;
            else if (type === 'opportunity') url = `/api/opportunities/${id}`;
            else if (type === 'post') url = `/api/community/${id}`;
            else if (type === 'bookmark') url = `/api/bookmarks/${id}`;
            else if (type === 'leaderboard_user') url = `/api/leaderboard/${id}`;

            await apiFetch(url, { method: 'DELETE' });
            showToast(`${capitalize(type === 'bookmark' ? 'Item' : type)} removed successfully`, 'success');

            smoothRemoveCard(element);
        } catch (err) {
            showToast(err.message, 'error');
        }
    }

    function smoothRemoveCard(element) {
        const card = element.closest('.timeline-card, .opp-feed-card, .social-card, .saved-card-wrapper, .timeline-node, .group-card');
        if (card) {
            card.classList.add('card-fade-out');
            setTimeout(() => {
                card.style.transition = 'all 0.3s ease';
                card.style.height = '0';
                card.style.margin = '0';
                card.style.padding = '0';
                setTimeout(() => card.remove(), 300);
            }, 300);
        }
    }

    function handleCopy(id, type, element) {
        let path = '';
        if (type === 'event') path = `/explore`; // Could be more specific if detail page exists
        else if (type === 'opportunity') path = `/opportunities`;
        else if (type === 'post') path = `/community/${id}`;
        
        // Ensure detail URLs if available
        if (type === 'event') path = `/explore`; // Note: events detail is modal-based usually
        
        const url = window.location.origin + path;
        navigator.clipboard.writeText(url).then(() => {
            showTooltip(element, 'Link copied!');
        });
    }

    function handleReport(id, type) {
        if (window.openReportModal) {
            // Attempt to find the title of the content item being reported
            let title = 'Untitled Item';
            const card = document.querySelector(`[data-id="${id}"]`)?.closest('.social-card, .timeline-card, .holographic-side-card, .forum-card-v2, .group-card, .event-card');
            
            if (card) {
                const titleEl = card.querySelector('.sc-title, .tc-title, .hsc-title, .card-v2-title, .group-title, .card-title, .hsc-header .hsc-title');
                if (titleEl) {
                    title = titleEl.innerText || titleEl.textContent;
                }
            }
            
            window.openReportModal(id, type, title.trim());
        }
    }

    function handleEdit(id, type) {
        if (type === 'post') {
            window.location.href = `/community/${id}?edit=true`;
        } else if (type === 'event') {
            window.location.href = `/explore?edit=${id}`;
        } else if (type === 'opportunity') {
            window.location.href = `/opportunities?edit=${id}`;
        }
    }

    async function handleHide(id, type, element) {
        const ogHTML = element.innerHTML;
        try {
            element.innerHTML = '<span>⏳</span> Hiding...';
            element.style.pointerEvents = 'none';

            let url = '';
            let method = 'POST';
            if (type === 'post') url = `/api/community/${id}/hide`;
            else if (type === 'event') url = `/api/events/${id}/hide`;
            else if (type === 'opportunity') {
                url = `/api/opportunities/${id}/hide`;
                method = 'PATCH';
            }
            else throw new Error("Hide action not supported for this type.");

            const response = await apiFetch(url, {
                method: method,
                body: JSON.stringify({ hide: true })
            });

            showToast(response.message || `${capitalize(type)} hidden successfully`, 'success');
            smoothRemoveCard(element);
        } catch (err) {
            console.error('Error hiding item:', err);
            showToast(err.message || 'Failed to hide item', 'error');
            element.innerHTML = ogHTML;
            element.style.pointerEvents = 'auto';
        }
    }

    // ─── UI Helpers ───

    function capitalize(s) {
        if (!s) return '';
        return s.charAt(0).toUpperCase() + s.slice(1);
    }

    function showTooltip(el, msg) {
        const tip = document.createElement('div');
        tip.className = 'copy-tooltip';
        tip.innerText = msg;
        document.body.appendChild(tip);
        
        const rect = el.getBoundingClientRect();
        tip.style.top = (rect.top + window.scrollY - 30) + 'px';
        tip.style.left = (rect.left + rect.width / 2) + 'px';
        tip.style.transform = 'translateX(-50%)';
        
        setTimeout(() => {
            tip.style.opacity = '0';
            setTimeout(() => tip.remove(), 300);
        }, 2000);
    }
});
