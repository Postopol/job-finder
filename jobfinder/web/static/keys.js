// Keyboard control. Keys are matched by physical position (e.code), so they work in
// both the Russian and the English layout. «?» shows the list of keys on any screen.
(function () {
  var FEED_KEYS = [
    ["↓  J", "следующая вакансия"],
    ["↑  K", "предыдущая вакансия"],
    ["→", "«Интересно» и дальше"],
    ["←", "«Не подходит» и дальше"],
    ["A", "«Откликнулся»"],
    ["Enter  O", "открыть оригинал"],
    ["/", "поиск"],
    ["1 2 3 4", "Лента, Мои, Архив, Скрытые"],
    ["Esc", "выйти из поиска"],
    ["?", "эта подсказка"],
  ];
  var TRIAGE_KEYS = [
    ["→", "интересно"],
    ["↓", "позже"],
    ["←", "не подходит"],
    ["Enter  O", "открыть оригинал"],
    ["?", "эта подсказка"],
  ];
  var TRIAGE_ACTIONS = { ArrowLeft: "reject", ArrowDown: "later", ArrowRight: "interesting" };
  var FEED_STATUS = { ArrowRight: "interesting", ArrowLeft: "rejected", KeyA: "applied" };
  var pendingNext = null; // {id, index}: open it once the list reloads after a status change
  var navigating = false; // the detail swap comes from a key: scroll it to the top

  function isFeed() { return !!document.getElementById("list"); }
  function isTriage() { return !!document.querySelector("[data-triage-action]"); }

  function typing(el) {
    return el && el.closest && el.closest("input, textarea, select, [contenteditable]");
  }

  // ---- help dialog

  var dialog = null;
  function helpDialog() {
    if (dialog) return dialog;
    dialog = document.createElement("dialog");
    dialog.className = "keys-help";
    dialog.setAttribute("aria-label", "Клавиши");
    var rows = (isFeed() ? FEED_KEYS : TRIAGE_KEYS).map(function (r) {
      return "<tr><td><kbd>" + r[0].split("  ").join("</kbd> <kbd>") + "</kbd></td><td>" +
        r[1] + "</td></tr>";
    }).join("");
    dialog.innerHTML = '<p class="keys-help__title">Клавиши</p><table>' + rows +
      '</table><p class="keys-help__note">Работают в русской и английской раскладке.</p>' +
      '<form method="dialog"><button class="qz-btn qz-btn--outline">Закрыть</button></form>';
    document.body.appendChild(dialog);
    return dialog;
  }
  function toggleHelp() {
    var d = helpDialog();
    if (d.open) d.close(); else d.showModal();
  }

  function addHintButton() {
    if (!isFeed() && !isTriage()) return;
    var b = document.createElement("button");
    b.type = "button";
    b.className = "keys-hint";
    b.title = "Управление с клавиатуры";
    b.innerHTML = "<kbd>?</kbd> Клавиши";
    b.addEventListener("click", toggleHelp);
    document.body.appendChild(b);
  }

  // ---- feed

  function items() { return Array.prototype.slice.call(document.querySelectorAll("#list .job-item")); }
  function selectedIndex(list) {
    for (var i = 0; i < list.length; i++) if (list[i].classList.contains("is-selected")) return i;
    return -1;
  }
  function openItem(item) {
    if (!item) return;
    navigating = true;
    item.click();
    item.focus({ preventScroll: true });
    item.scrollIntoView({ block: "nearest" });
  }
  function move(delta) {
    var list = items();
    if (!list.length) return;
    var i = selectedIndex(list);
    var next = i < 0 ? 0 : Math.min(Math.max(i + delta, 0), list.length - 1);
    if (next !== i) openItem(list[next]);
  }
  function setStatus(status, advance) {
    var button = document.querySelector('#detail button[name="status"][value="' + status + '"]');
    if (!button) return false;
    if (advance) {
      var list = items();
      var i = selectedIndex(list);
      var next = list[i + 1];
      pendingNext = { id: next ? next.dataset.jobId : null, index: i };
    }
    button.click();
    return true;
  }
  function openOriginal() {
    var link = document.querySelector("#detail .actions a.qz-btn--primary, .triage-links__original");
    if (!link) return false;
    window.open(link.href, "_blank", "noopener");
    return true;
  }
  function section(n) {
    var tab = document.querySelectorAll('#list [role="tab"]')[n];
    if (tab) tab.click();
  }

  document.addEventListener("htmx:afterSwap", function (e) {
    var target = e.detail.target;
    if (target.id === "list" && pendingNext) {
      var p = pendingNext;
      pendingNext = null;
      var list = items();
      var item = p.id && document.querySelector('#list .job-item[data-job-id="' + p.id + '"]');
      if (!item) item = list[Math.min(p.index, list.length - 1)]; // the marked one left the list
      if (item && !item.classList.contains("is-selected")) openItem(item);
    } else if (target.id === "detail" && navigating) {
      navigating = false;
      target.scrollTop = 0;
    }
  });

  // ---- keys

  function onFeedKey(e) {
    switch (e.code) {
      case "ArrowDown": case "KeyJ": move(1); return true;
      case "ArrowUp": case "KeyK": move(-1); return true;
      case "ArrowRight": case "ArrowLeft": case "KeyA":
        return setStatus(FEED_STATUS[e.code], e.code !== "KeyA");
      case "Enter": case "KeyO": return openOriginal();
      case "Slash": var q = document.getElementById("q"); if (q) { q.focus(); q.select(); } return !!q;
      case "Digit1": case "Digit2": case "Digit3": case "Digit4":
        section(Number(e.code.slice(5)) - 1); return true;
    }
    return false;
  }
  function onTriageKey(e) {
    var action = TRIAGE_ACTIONS[e.code];
    if (action) {
      if (e.repeat) return true;
      var button = document.querySelector('[data-triage-action="' + action + '"]');
      if (button && !button.disabled) button.click();
      return true;
    }
    if (e.code === "Enter" || e.code === "KeyO") return openOriginal();
    return false;
  }

  document.addEventListener("keydown", function (e) {
    if (e.altKey || e.ctrlKey || e.metaKey) return;
    var el = e.target;
    if (e.key === "Escape" && typing(el)) { el.blur(); return; }
    if (typing(el)) return;
    if (e.key === "?") { e.preventDefault(); toggleHelp(); return; }
    if (dialog && dialog.open) return; // Esc closes it natively
    if (e.shiftKey) return;
    // Enter on a button or a menu keeps its own meaning; on a list item the job is open already
    if (e.code === "Enter" && el.closest && el.closest("button, summary, a:not(.job-item)")) return;
    var handled = isFeed() ? onFeedKey(e) : isTriage() ? onTriageKey(e) : false;
    if (handled) e.preventDefault();
  });

  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", addHintButton);
  else addHintButton();
})();
