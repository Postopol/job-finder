// Triage hotkeys: ← не подходит, ↓ позже, → интересно.
(function () {
  var ACTIONS = { ArrowLeft: "reject", ArrowDown: "later", ArrowRight: "interesting" };
  document.addEventListener("keydown", function (e) {
    var action = ACTIONS[e.key];
    if (!action || e.repeat || e.altKey || e.ctrlKey || e.metaKey || e.shiftKey) return;
    var el = e.target;
    if (el && el.closest && el.closest("input, textarea, select, [contenteditable]")) return;
    var button = document.querySelector('[data-triage-action="' + action + '"]');
    if (!button || button.disabled) return;
    e.preventDefault();
    button.click();
  });
})();
