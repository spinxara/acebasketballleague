(function () {
  var grid = document.querySelector("[data-moment-grid]");
  var input = document.getElementById("moment-order");
  var save = document.getElementById("moment-order-save");
  if (!grid || !input || !save) {
    return;
  }

  var dragged = null;
  var saved = input.value;

  function writeOrder() {
    var ids = Array.prototype.map.call(
      grid.querySelectorAll("[data-moment-id]"),
      function (card) {
        return card.getAttribute("data-moment-id");
      }
    );
    var next = ids.join(",");
    input.value = next;
    save.disabled = saved === next;
  }

  grid.addEventListener("click", function (event) {
    var button = event.target.closest("[data-move]");
    if (!button) {
      return;
    }
    var card = button.closest("[data-moment-id]");
    if (!card) {
      return;
    }
    if (button.getAttribute("data-move") === "earlier") {
      var previous = card.previousElementSibling;
      if (previous) {
        grid.insertBefore(card, previous);
      }
    } else if (card.nextElementSibling) {
      grid.insertBefore(card.nextElementSibling, card);
    }
    writeOrder();
  });

  grid.addEventListener("dragstart", function (event) {
    var handle = event.target.closest("[data-moment-drag]");
    var card = handle && handle.closest("[data-moment-id]");
    if (!card) {
      event.preventDefault();
      return;
    }
    dragged = card;
    card.classList.add("is-dragging");
    event.dataTransfer.effectAllowed = "move";
    event.dataTransfer.setData("text/plain", card.getAttribute("data-moment-id"));
  });

  grid.addEventListener("dragover", function (event) {
    if (!dragged) {
      return;
    }
    event.preventDefault();
    var card = event.target.closest("[data-moment-id]");
    if (!card || card === dragged) {
      return;
    }
    var rect = card.getBoundingClientRect();
    var after = event.clientX > rect.left + rect.width / 2;
    grid.insertBefore(dragged, after ? card.nextSibling : card);
  });

  grid.addEventListener("drop", function (event) {
    event.preventDefault();
    writeOrder();
  });

  grid.addEventListener("dragend", function () {
    if (dragged) {
      dragged.classList.remove("is-dragging");
    }
    dragged = null;
    writeOrder();
  });
})();
