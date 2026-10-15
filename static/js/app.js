// Line-item grids: "+ Add line" clones the formset's empty form.
document.querySelectorAll(".add-row").forEach(function (btn) {
  btn.addEventListener("click", function () {
    var table = btn.parentElement.querySelector("table.lines");
    var prefix = table.dataset.prefix;
    var total = document.getElementById("id_" + prefix + "-TOTAL_FORMS");
    var index = parseInt(total.value, 10);
    var html = table.querySelector("template").innerHTML.replace(/__prefix__/g, index);
    table.querySelector("tbody").insertAdjacentHTML("beforeend", html);
    total.value = index + 1;
  });
});

// Workflow buttons: optional confirmation and comment prompt.
document.querySelectorAll("form.action-form").forEach(function (form) {
  form.addEventListener("submit", function (e) {
    if (form.dataset.confirm && !window.confirm(form.dataset.confirm)) {
      e.preventDefault();
      return;
    }
    if (form.dataset.prompt) {
      var value = window.prompt(form.dataset.prompt, "");
      if (value === null) { e.preventDefault(); return; }
      form.querySelector("input[name=comment]").value = value;
    }
  });
});
