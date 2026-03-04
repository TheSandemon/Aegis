/* mentions.js — @mention autocomplete picker for Aegis text inputs */

(function () {
    let dropdown = null;
    let activeInput = null;
    let mentionStart = -1;
    let selectedIdx = 0;
    let filteredOptions = [];

    // ─── Dropdown DOM ────────────────────────────────────────────────────────

    function createDropdown() {
        const el = document.createElement('div');
        el.className = 'mention-dropdown';
        el.style.display = 'none';
        document.body.appendChild(el);
        return el;
    }

    function getDropdown() {
        if (!dropdown) dropdown = createDropdown();
        return dropdown;
    }

    function showDropdown(inputEl, options) {
        filteredOptions = options;
        selectedIdx = 0;
        const dd = getDropdown();
        if (!options.length) { hideDropdown(); return; }

        dd.innerHTML = options.map((opt, i) =>
            `<div class="mention-option ${i === 0 ? 'selected' : ''}" data-idx="${i}">
                <span class="mention-type-badge">${opt.typeLabel}</span>
                <span class="mention-label">${escapeHtml(opt.label)}</span>
            </div>`
        ).join('');

        // Position below cursor
        const rect = inputEl.getBoundingClientRect();
        const lineHeight = parseInt(getComputedStyle(inputEl).lineHeight) || 20;
        dd.style.left = `${rect.left + window.scrollX}px`;
        dd.style.top = `${rect.bottom + window.scrollY + 4}px`;
        dd.style.display = 'block';

        // Click to select
        dd.querySelectorAll('.mention-option').forEach(el => {
            el.addEventListener('mousedown', e => {
                e.preventDefault();
                selectOption(parseInt(el.dataset.idx));
            });
        });
    }

    function hideDropdown() {
        const dd = getDropdown();
        dd.style.display = 'none';
        filteredOptions = [];
        mentionStart = -1;
        activeInput = null;
    }

    function updateSelection() {
        const dd = getDropdown();
        dd.querySelectorAll('.mention-option').forEach((el, i) => {
            el.classList.toggle('selected', i === selectedIdx);
        });
        const sel = dd.querySelector('.mention-option.selected');
        if (sel) sel.scrollIntoView({ block: 'nearest' });
    }

    function selectOption(idx) {
        if (!activeInput || idx < 0 || idx >= filteredOptions.length) return;
        const opt = filteredOptions[idx];
        const val = activeInput.value;
        const before = val.slice(0, mentionStart);
        const after = val.slice(activeInput.selectionStart);
        activeInput.value = before + opt.insertText + ' ' + after;
        const newPos = (before + opt.insertText + ' ').length;
        activeInput.setSelectionRange(newPos, newPos);
        activeInput.dispatchEvent(new Event('input'));
        hideDropdown();
    }

    // ─── Options ─────────────────────────────────────────────────────────────

    function buildOptions(query) {
        const q = query.toLowerCase();
        const opts = [];

        // Cards — @#42 Title
        if (typeof cards !== 'undefined') {
            cards.forEach(c => {
                const label = `#${c.id} ${c.title}`;
                if (!q || label.toLowerCase().includes(q) || String(c.id).startsWith(q)) {
                    opts.push({ typeLabel: 'card', label, insertText: `@${c.id}`, priority: 0 });
                }
            });
        }

        // Columns — @Column Name
        if (typeof columns !== 'undefined') {
            columns.forEach(col => {
                if (!q || col.name.toLowerCase().includes(q)) {
                    opts.push({ typeLabel: 'col', label: col.name, insertText: `@${col.name}`, priority: 1 });
                }
            });
        }

        // Agents — @agent-name
        if (typeof instancesData !== 'undefined') {
            instancesData.forEach(inst => {
                const name = inst.instance_name || inst.agent_id;
                if (!q || name.toLowerCase().includes(q)) {
                    opts.push({ typeLabel: 'agent', label: name, insertText: `@${name}`, priority: 2 });
                }
            });
        }

        // Sort: priority first, then alphabetical within type
        opts.sort((a, b) => a.priority - b.priority || a.label.localeCompare(b.label));
        return opts.slice(0, 8);
    }

    // ─── Input handling ───────────────────────────────────────────────────────

    function handleKeydown(e) {
        const dd = getDropdown();
        if (dd.style.display === 'none') return;

        if (e.key === 'ArrowDown') {
            e.preventDefault();
            selectedIdx = Math.min(selectedIdx + 1, filteredOptions.length - 1);
            updateSelection();
        } else if (e.key === 'ArrowUp') {
            e.preventDefault();
            selectedIdx = Math.max(selectedIdx - 1, 0);
            updateSelection();
        } else if (e.key === 'Enter' || e.key === 'Tab') {
            if (filteredOptions.length) {
                e.preventDefault();
                selectOption(selectedIdx);
            }
        } else if (e.key === 'Escape') {
            hideDropdown();
        }
    }

    function handleInput(e) {
        const el = e.target;
        const val = el.value;
        const cursor = el.selectionStart;

        // Find the nearest @ before the cursor on the same line
        let atIdx = -1;
        for (let i = cursor - 1; i >= 0; i--) {
            if (val[i] === '@') { atIdx = i; break; }
            if (val[i] === ' ' || val[i] === '\n') break;
        }

        if (atIdx === -1) { hideDropdown(); return; }

        const query = val.slice(atIdx + 1, cursor);
        if (query.length > 30) { hideDropdown(); return; }

        mentionStart = atIdx;
        activeInput = el;
        const opts = buildOptions(query);
        showDropdown(el, opts);
    }

    function handleBlur() {
        // Delay so mousedown on option fires first
        setTimeout(hideDropdown, 150);
    }

    // ─── Attach ───────────────────────────────────────────────────────────────

    function attachMentionPicker(el) {
        if (!el || el._mentionAttached) return;
        el._mentionAttached = true;
        el.addEventListener('input', handleInput);
        el.addEventListener('keydown', handleKeydown);
        el.addEventListener('blur', handleBlur);
    }

    // ─── Auto-attach to known inputs + observe DOM for dynamic ones ───────────

    function attachAll() {
        const ids = ['cardDescription', 'detailDescription'];
        ids.forEach(id => {
            const el = document.getElementById(id);
            if (el) attachMentionPicker(el);
        });
        // Attach to any textarea with data-mention="true"
        document.querySelectorAll('textarea[data-mention]').forEach(attachMentionPicker);
    }

    // Observe for dynamically added textareas
    const observer = new MutationObserver(() => attachAll());

    // Public API
    window.attachMentionPicker = attachMentionPicker;
    window.mentionPickerInit = function () {
        attachAll();
        observer.observe(document.body, { childList: true, subtree: true });
    };

    // ─── Utility ─────────────────────────────────────────────────────────────

    function escapeHtml(str) {
        return String(str).replace(/&/g, '&amp;').replace(/</g, '&lt;').replace(/>/g, '&gt;');
    }

    document.addEventListener('DOMContentLoaded', window.mentionPickerInit);
})();
