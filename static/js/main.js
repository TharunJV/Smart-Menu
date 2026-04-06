/* Smart Menu — main.js */
document.addEventListener("DOMContentLoaded", () => {

  // ── Auto-dismiss flash messages ──────────────────
  document.querySelectorAll(".flash").forEach(el => {
    setTimeout(() => {
      el.style.transition = "opacity .4s, transform .4s";
      el.style.opacity    = "0";
      el.style.transform  = "translateY(-8px)";
      setTimeout(() => el.remove(), 400);
    }, 4000);
  });

});

// ── Mobile sidebar ───────────────────────────────────
function openSidebar() {
  document.getElementById("sidebar").classList.add("open");
  document.getElementById("sidebarOverlay").classList.add("open");
  document.body.style.overflow = "hidden";
}
function closeSidebar() {
  document.getElementById("sidebar").classList.remove("open");
  document.getElementById("sidebarOverlay").classList.remove("open");
  document.body.style.overflow = "";
}

// Close sidebar on nav click (mobile)
document.addEventListener("DOMContentLoaded", () => {
  document.querySelectorAll(".nav-link").forEach(link => {
    link.addEventListener("click", () => {
      if (window.innerWidth <= 768) closeSidebar();
    });
  });
});
