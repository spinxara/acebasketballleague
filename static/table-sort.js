(function () {
  function toNumber(text) {
    if (!text) {
      return null;
    }
    var value = Number(text.replace(/[%,]/g, ""));
    return Number.isFinite(value) ? value : null;
  }

  function compareCells(left, right) {
    var leftNumber = toNumber(left);
    var rightNumber = toNumber(right);

    if (leftNumber !== null && rightNumber !== null) {
      return leftNumber - rightNumber;
    }
    if (leftNumber !== null) {
      return -1;
    }
    if (rightNumber !== null) {
      return 1;
    }
    return left.localeCompare(right);
  }

  function nextDirection(header) {
    var current = header.getAttribute("aria-sort");
    if (current === "ascending") {
      return "descending";
    }
    if (current === "descending") {
      return "ascending";
    }
    return header.classList.contains("numeric") ? "descending" : "ascending";
  }

  function setupTable(table) {
    var body = table.tBodies[0];
    if (!body) {
      return;
    }

    var headers = Array.prototype.slice.call(table.querySelectorAll("thead th"));

    headers.forEach(function (header, index) {
      var button = header.querySelector(".sort-btn");
      if (!button) {
        return;
      }

      button.addEventListener("click", function () {
        var direction = nextDirection(header);
        var factor = direction === "ascending" ? 1 : -1;
        var rows = Array.prototype.slice.call(body.rows);

        rows.sort(function (a, b) {
          var left = a.cells[index].textContent.trim();
          var right = b.cells[index].textContent.trim();
          return compareCells(left, right) * factor;
        });

        headers.forEach(function (other) {
          other.removeAttribute("aria-sort");
        });
        header.setAttribute("aria-sort", direction);

        rows.forEach(function (row) {
          body.appendChild(row);
        });
      });
    });
  }

  Array.prototype.slice
    .call(document.querySelectorAll(".sortable-table"))
    .forEach(setupTable);
})();
