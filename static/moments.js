(function () {
  const lightbox = document.querySelector("[data-lightbox]");
  if (!lightbox) {
    return;
  }

  const image = lightbox.querySelector("[data-lightbox-image]");
  const caption = lightbox.querySelector("[data-lightbox-caption]");
  const closeButtons = lightbox.querySelectorAll("[data-lightbox-close]");

  function closeLightbox() {
    lightbox.classList.remove("open");
    lightbox.setAttribute("aria-hidden", "true");
    if (image) {
      image.removeAttribute("src");
      image.alt = "";
    }
    if (caption) {
      caption.textContent = "";
    }
  }

  function openLightbox(src, text) {
    if (!image || !src) {
      return;
    }
    image.src = src;
    image.alt = text || "Team moment";
    if (caption) {
      caption.textContent = text || "";
      caption.hidden = !text;
    }
    lightbox.setAttribute("aria-hidden", "false");
    lightbox.classList.add("open");
  }

  document.querySelectorAll("[data-lightbox-open]").forEach(function (button) {
    button.addEventListener("click", function () {
      openLightbox(button.getAttribute("data-src"), button.getAttribute("data-caption"));
    });
  });

  closeButtons.forEach(function (button) {
    button.addEventListener("click", closeLightbox);
  });

  lightbox.addEventListener("click", function (event) {
    if (event.target === lightbox) {
      closeLightbox();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (event.key === "Escape" && lightbox.classList.contains("open")) {
      closeLightbox();
    }
  });
})();
