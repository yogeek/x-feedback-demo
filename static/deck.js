// Slide navigation (buttons, arrow keys, swipe, #n in the URL) and the
// "two ways to answer" replay on the duel slide.
const slides = [...document.querySelectorAll(".slide")];
const prev = document.getElementById("prev");
const next = document.getElementById("next");
const count = document.getElementById("count");
const progress = document.getElementById("progress");
const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
let index = 0;

document.documentElement.classList.add("js");

function show(i, push = true) {
  index = Math.max(0, Math.min(slides.length - 1, i));
  slides.forEach((s, k) => s.classList.toggle("current", k === index));
  prev.disabled = index === 0;
  next.disabled = index === slides.length - 1;
  count.textContent = `${index + 1} / ${slides.length}`;
  progress.style.width = `${((index + 1) / slides.length) * 100}%`;
  if (push) history.replaceState(null, "", `#${index + 1}`);
  window.scrollTo(0, 0);
  if (slides[index].contains(duel.typed)) duel.play();
  else duel.stop();
}

prev.addEventListener("click", () => show(index - 1));
next.addEventListener("click", () => show(index + 1));
document.addEventListener("keydown", (e) => {
  if (e.altKey || e.ctrlKey || e.metaKey) return;
  if (["ArrowRight", "PageDown"].includes(e.key) || (e.key === " " && !e.shiftKey)) {
    e.preventDefault(); show(index + 1);
  } else if (["ArrowLeft", "PageUp"].includes(e.key) || (e.key === " " && e.shiftKey)) {
    e.preventDefault(); show(index - 1);
  } else if (e.key === "Home") { show(0); }
  else if (e.key === "End") { show(slides.length - 1); }
});
let touchX = null;
document.addEventListener("touchstart", (e) => { touchX = e.touches[0].clientX; }, { passive: true });
document.addEventListener("touchend", (e) => {
  if (touchX === null) return;
  const dx = e.changedTouches[0].clientX - touchX;
  touchX = null;
  if (Math.abs(dx) > 60) show(index + (dx < 0 ? 1 : -1));
});
window.addEventListener("hashchange", () => show(parseInt(location.hash.slice(1), 10) - 1 || 0, false));

// The LLM side shows its tokens one by one; the decision side fills all bars at once.
const duel = {
  typed: document.getElementById("typed"),
  bars: document.getElementById("bars"),
  tokens: ['{"', "opinion", '":', ' "', "mixed", '"}'],
  timers: [],
  stop() { this.timers.forEach(clearTimeout); this.timers = []; },
  play() {
    this.stop();
    const { typed, bars, tokens } = this;
    if (reduced) { typed.textContent = tokens.join(""); bars.classList.remove("empty"); return; }
    typed.textContent = "";
    typed.classList.add("typing");
    bars.classList.add("empty");
    this.timers.push(setTimeout(() => bars.classList.remove("empty"), 500));
    tokens.forEach((t, k) => this.timers.push(setTimeout(() => {
      const span = document.createElement("span");
      span.className = "tok";
      span.textContent = t;
      typed.append(span);
      if (k === tokens.length - 1) typed.classList.remove("typing");
    }, 900 + k * 550)));
  },
};
document.getElementById("play").addEventListener("click", () => duel.play());

show(parseInt(location.hash.slice(1), 10) - 1 || 0, false);
