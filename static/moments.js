(function () {
  const lightbox = document.querySelector("[data-lightbox]");
  if (!lightbox) {
    return;
  }

  const image = lightbox.querySelector("[data-lightbox-image]");
  const caption = lightbox.querySelector("[data-lightbox-caption]");
  const counter = lightbox.querySelector("[data-lightbox-counter]");
  const prevButton = lightbox.querySelector("[data-lightbox-prev]");
  const nextButton = lightbox.querySelector("[data-lightbox-next]");
  const closeButtons = lightbox.querySelectorAll("[data-lightbox-close]");
  const items = Array.from(document.querySelectorAll("[data-lightbox-open]"));
  let currentIndex = 0;

  function isOpen() {
    return lightbox.classList.contains("open");
  }

  function showPhoto(index) {
    if (!image || !items.length) {
      return;
    }
    currentIndex = (index + items.length) % items.length;
    const button = items[currentIndex];
    const src = button.getAttribute("data-src");
    const text = button.getAttribute("data-caption") || "";
    if (!src) {
      return;
    }
    image.src = src;
    image.alt = text || "Team moment";
    if (caption) {
      caption.textContent = text;
      caption.hidden = !text;
    }
    if (counter) {
      counter.textContent = currentIndex + 1 + " / " + items.length;
      counter.hidden = items.length < 2;
    }
    const many = items.length > 1;
    if (prevButton) {
      prevButton.hidden = !many;
    }
    if (nextButton) {
      nextButton.hidden = !many;
    }
  }

  function openLightbox(index) {
    showPhoto(index);
    lightbox.setAttribute("aria-hidden", "false");
    lightbox.classList.add("open");
  }

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

  function showNext() {
    showPhoto(currentIndex + 1);
  }

  function showPrevious() {
    showPhoto(currentIndex - 1);
  }

  items.forEach(function (button, index) {
    button.addEventListener("click", function () {
      openLightbox(index);
    });
  });

  if (prevButton) {
    prevButton.addEventListener("click", showPrevious);
  }
  if (nextButton) {
    nextButton.addEventListener("click", showNext);
  }

  closeButtons.forEach(function (button) {
    button.addEventListener("click", closeLightbox);
  });

  lightbox.addEventListener("click", function (event) {
    if (event.target === lightbox) {
      closeLightbox();
    }
  });

  document.addEventListener("keydown", function (event) {
    if (!isOpen()) {
      return;
    }
    if (event.key === "Escape") {
      closeLightbox();
    } else if (event.key === "ArrowRight") {
      event.preventDefault();
      showNext();
    } else if (event.key === "ArrowLeft") {
      event.preventDefault();
      showPrevious();
    }
  });
})();
