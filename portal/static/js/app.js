/* Azure News Portal - minimal progressive enhancement (no external dependencies) */
(function () {
  'use strict';

  /* ------------------------------------------------------------------ theme */

  var STORAGE_KEY = 'anp-theme';
  var root = document.documentElement;

  function applyTheme(theme) {
    root.setAttribute('data-theme', theme);
    var toggle = document.getElementById('theme-toggle');
    if (toggle) {
      toggle.setAttribute('aria-pressed', theme === 'dark' ? 'true' : 'false');
    }
  }

  function initialTheme() {
    try {
      var stored = window.localStorage.getItem(STORAGE_KEY);
      if (stored === 'light' || stored === 'dark') {
        return stored;
      }
    } catch (err) {
      /* localStorage が使えない環境では既定値を使う */
    }
    return window.matchMedia && window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light';
  }

  applyTheme(initialTheme());

  document.addEventListener('click', function (event) {
    var toggle = event.target.closest('#theme-toggle');
    if (!toggle) {
      return;
    }
    var next = root.getAttribute('data-theme') === 'dark' ? 'light' : 'dark';
    applyTheme(next);
    try {
      window.localStorage.setItem(STORAGE_KEY, next);
    } catch (err) {
      /* 保存できなくても動作を継続する */
    }
  });

  /* ------------------------------------------------------------- load more */

  var loadMoreButton = document.getElementById('load-more');
  var grid = document.getElementById('article-grid');

  function buildUrl(base, cursor) {
    var url = '/partials/articles';
    var query = base ? base : '';
    if (cursor) {
      query = query ? query + '&cursor=' + encodeURIComponent(cursor) : 'cursor=' + encodeURIComponent(cursor);
    }
    return query ? url + '?' + query : url;
  }

  if (loadMoreButton && grid) {
    loadMoreButton.addEventListener('click', function () {
      var cursor = loadMoreButton.getAttribute('data-next-cursor');
      var base = loadMoreButton.getAttribute('data-base-query') || '';
      if (!cursor || loadMoreButton.disabled) {
        return;
      }
      loadMoreButton.disabled = true;
      loadMoreButton.textContent = '読み込み中...';

      fetch(buildUrl(base, cursor), { headers: { Accept: 'text/html' } })
        .then(function (response) {
          if (!response.ok) {
            throw new Error('failed to load articles');
          }
          return response.text();
        })
        .then(function (html) {
          var template = document.createElement('template');
          template.innerHTML = html;
          var marker = template.content.querySelector('.load-more-marker');
          var nextCursor = marker ? marker.getAttribute('data-next-cursor') : '';
          if (marker) {
            marker.remove();
          }
          var placeholder = template.content.querySelector('[data-empty="true"]');
          if (placeholder) {
            placeholder.remove();
          }
          grid.appendChild(template.content);

          if (nextCursor) {
            loadMoreButton.setAttribute('data-next-cursor', nextCursor);
            loadMoreButton.disabled = false;
            loadMoreButton.textContent = 'さらに読み込む';
          } else {
            loadMoreButton.remove();
          }
        })
        .catch(function () {
          loadMoreButton.disabled = false;
          loadMoreButton.textContent = '再試行';
        });
    });
  }

  /* ----------------------------------------------------------------- modal */

  var modal = document.getElementById('article-modal');
  var modalBody = document.getElementById('article-modal-body');
  var lastFocused = null;

  function closeModal() {
    if (!modal || modal.hidden) {
      return;
    }
    modal.hidden = true;
    if (modalBody) {
      modalBody.innerHTML = '';
    }
    document.body.style.removeProperty('overflow');
    if (lastFocused && typeof lastFocused.focus === 'function') {
      lastFocused.focus();
    }
  }

  function openModal(articleId, trigger) {
    if (!modal || !modalBody) {
      return;
    }
    lastFocused = trigger || null;
    modalBody.textContent = '読み込み中...';
    modal.hidden = false;
    document.body.style.overflow = 'hidden';

    fetch('/partials/articles/' + encodeURIComponent(articleId), { headers: { Accept: 'text/html' } })
      .then(function (response) {
        if (!response.ok) {
          throw new Error('failed to load article');
        }
        return response.text();
      })
      .then(function (html) {
        modalBody.innerHTML = html;
        var closeButton = modal.querySelector('.modal__close');
        if (closeButton) {
          closeButton.focus();
        }
      })
      .catch(function () {
        modalBody.textContent = '記事を読み込めませんでした。ページを再読み込みしてください。';
      });
  }

  document.addEventListener('click', function (event) {
    if (event.target.closest('[data-modal-close]')) {
      closeModal();
      return;
    }

    var link = event.target.closest('[data-article-id]');
    if (!link || event.metaKey || event.ctrlKey || event.shiftKey || event.button !== 0) {
      return;
    }
    var articleId = link.getAttribute('data-article-id');
    if (!articleId || !modal) {
      return;
    }
    event.preventDefault();
    openModal(articleId, link);
  });

  document.addEventListener('keydown', function (event) {
    if (event.key === 'Escape') {
      closeModal();
    }
  });
})();
