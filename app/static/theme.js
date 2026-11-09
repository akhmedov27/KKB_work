// Storage can be unavailable in restricted browser profiles.
try {
  if (localStorage.getItem('qms-theme') === 'dark') {
    document.documentElement.dataset.theme = 'dark';
  }
} catch { /* The light theme remains available without storage. */ }
