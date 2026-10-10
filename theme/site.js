// Eser resmine tıklayınca tam ekran göster
(function () {
  var lb = document.getElementById("lb");
  if (!lb) return;
  var img = lb.querySelector("img");
  document.querySelectorAll(".images .big").forEach(function (a) {
    a.addEventListener("click", function (e) {
      e.preventDefault();
      img.src = a.href;
      lb.classList.add("on");
    });
  });
  lb.addEventListener("click", function () { lb.classList.remove("on"); });
  document.addEventListener("keydown", function (e) { if (e.key === "Escape") lb.classList.remove("on"); });
})();
