/**
 * Shared formatting helpers.
 */

/** Escape text for interpolation into innerHTML.
 *
 *  Everything rendered through it is corpus text -- headwords, article
 *  prose, reference phrases -- which contains angle brackets, ampersands
 *  and quotation marks of its own.
 */
export function escapeHtml(text) {
  return String(text ?? '').replace(/[&<>"']/g, (c) => (
    { '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]
  ));
}
