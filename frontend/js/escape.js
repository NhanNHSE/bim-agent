/**
 * Global HTML escape utility to prevent XSS.
 * Converts null/undefined to empty string and escapes &, <, >, ", '.
 *
 * @param {any} value
 * @returns {string}
 */
function escapeHtml(value) {
    if (value === null || value === undefined) {
        return '';
    }
    return String(value)
        .replace(/&/g, '&amp;')
        .replace(/</g, '&lt;')
        .replace(/>/g, '&gt;')
        .replace(/"/g, '&quot;')
        .replace(/'/g, '&#39;');
}

if (typeof window !== 'undefined') {
    window.escapeHtml = escapeHtml;
}
if (typeof module !== 'undefined' && module.exports) {
    module.exports = { escapeHtml };
}
