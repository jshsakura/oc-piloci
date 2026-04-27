(function () {
  try {
    var storageKey = "piloci-theme";
    var storedTheme = window.localStorage.getItem(storageKey);
    var systemPrefersDark =
      typeof window.matchMedia === "function" &&
      window.matchMedia("(prefers-color-scheme: dark)").matches;
    var theme =
      storedTheme === "dark" || storedTheme === "light"
        ? storedTheme
        : systemPrefersDark
          ? "dark"
          : "light";
    var root = document.documentElement;
    root.classList.toggle("dark", theme === "dark");
    root.style.colorScheme = theme;
  } catch {
    var root = document.documentElement;
    root.classList.remove("dark");
    root.style.colorScheme = "light";
  }
})();
