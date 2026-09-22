(function () {
  var barCount = 0;

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

  function defaultDirection(header) {
    return header.classList.contains("numeric") ? "descending" : "ascending";
  }

  function nextDirection(header) {
    var current = header.getAttribute("aria-sort");
    if (current === "ascending") {
      return "descending";
    }
    if (current === "descending") {
      return "ascending";
    }
    return defaultDirection(header);
  }

  function directionLabel(header, direction) {
    var numeric = header.classList.contains("numeric");
    if (direction === "ascending") {
      return numeric ? "Low to High" : "A to Z";
    }
    return numeric ? "High to Low" : "Z to A";
  }

  function buildSortBar(table, headers, applySort) {
    var sortable = headers.filter(function (header) {
      return Boolean(header.querySelector(".sort-btn"));
    });

    if (!sortable.length) {
      return null;
    }

    barCount += 1;

    var bar = document.createElement("div");
    bar.className = "sort-bar";

    var field = document.createElement("div");
    field.className = "sort-field";

    var select = document.createElement("select");
    select.id = "table-sort-" + barCount;

    var label = document.createElement("label");
    label.setAttribute("for", select.id);
    label.textContent = "Sort by";

    sortable.forEach(function (header) {
      var option = document.createElement("option");
      option.value = String(headers.indexOf(header));
      option.textContent = header.textContent.trim();
      select.appendChild(option);
    });

    var dirButton = document.createElement("button");
    dirButton.type = "button";
    dirButton.className = "sort-dir";
    dirButton.setAttribute("aria-label", "Change sort direction");

    field.appendChild(label);
    field.appendChild(select);
    bar.appendChild(field);
    bar.appendChild(dirButton);

    var anchor = table;
    if (table.parentNode.classList && table.parentNode.classList.contains("table-wrap")) {
      anchor = table.parentNode;
    }
    anchor.parentNode.insertBefore(bar, anchor);

    var direction = defaultDirection(headers[Number(select.value)]);

    function refreshButton() {
      dirButton.textContent = directionLabel(headers[Number(select.value)], direction);
    }

    select.addEventListener("change", function () {
      var index = Number(select.value);
      direction = defaultDirection(headers[index]);
      refreshButton();
      applySort(index, direction);
    });

    dirButton.addEventListener("click", function () {
      var index = Number(select.value);
      direction = direction === "ascending" ? "descending" : "ascending";
      refreshButton();
      applySort(index, direction);
    });

    refreshButton();

    return {
      sync: function (index, nextDir) {
        select.value = String(index);
        direction = nextDir;
        refreshButton();
      }
    };
  }

  function setupTable(table) {
    var body = table.tBodies[0];
    if (!body) {
      return;
    }

    var headers = Array.prototype.slice.call(table.querySelectorAll("thead th"));

    function applySort(index, direction) {
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
      headers[index].setAttribute("aria-sort", direction);

      rows.forEach(function (row) {
        body.appendChild(row);
      });
    }

    var sortBar = buildSortBar(table, headers, applySort);

    headers.forEach(function (header, index) {
      var button = header.querySelector(".sort-btn");
      if (!button) {
        return;
      }

      button.addEventListener("click", function () {
        var direction = nextDirection(header);
        applySort(index, direction);
        if (sortBar) {
          sortBar.sync(index, direction);
        }
      });
    });
  }

  Array.prototype.slice
    .call(document.querySelectorAll(".sortable-table"))
    .forEach(setupTable);
})();
