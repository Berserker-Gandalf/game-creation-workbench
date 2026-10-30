export function setupMotion(onChange) {
  const root = document.documentElement, toggle = document.querySelector('#motion-toggle');
  toggle.hidden = false;
  const reduced = matchMedia('(prefers-reduced-motion: reduce)'), pointer = matchMedia('(hover: hover) and (pointer: fine)');
  const showcase = document.querySelector('.hero-showcase');
  let enabled = false, preference = true, frame = 0, pointerFrame = 0, revealObserver, bounds;
  try { preference = localStorage.getItem('zaowu-site-motion') !== 'off'; } catch {}
  const revealNodes = [...document.querySelectorAll('.section-heading, .feature-grid article, .workflow li, .preview-frame, .download-card, .questions>div, .hero-copy, .hero-showcase')];
  revealNodes.forEach((node, i) => { node.classList.add('reveal'); node.style.setProperty('--reveal-delay', (i % 3) * 65 + 'ms'); });

  function resetPointer() {
    cancelAnimationFrame(pointerFrame); pointerFrame = 0; bounds = null;
    showcase.style.removeProperty('--tilt-x'); showcase.style.removeProperty('--tilt-y'); showcase.style.removeProperty('--light-on');
  }
  function updateScroll() {
    frame = 0;
    const distance = root.scrollHeight - root.clientHeight;
    root.style.setProperty('--scroll-progress', enabled && distance > 0 ? Math.min(1,Math.max(0,scrollY / distance)) : 0);
    if (scrollY < 64) document.querySelectorAll('.site-header nav [aria-current]').forEach(link => link.removeAttribute('aria-current'));
  }
  function refresh() {
    enabled = preference && !reduced.matches;
    root.classList.toggle('motion-enabled', enabled);
    toggle.setAttribute('aria-pressed', String(enabled)); toggle.disabled = reduced.matches;
    revealObserver?.disconnect();
    if (enabled && typeof IntersectionObserver !== 'undefined') {
      revealObserver = new IntersectionObserver(entries => entries.forEach(entry => {
        if (!entry.isIntersecting) return;
        entry.target.classList.remove('reveal-pending'); entry.target.dataset.revealed = 'true'; revealObserver.unobserve(entry.target);
      }), {threshold:.08});
      for (const node of revealNodes) if (!node.dataset.revealed) { node.classList.add('reveal-pending'); revealObserver.observe(node); }
    } else {
      revealNodes.forEach(node => { node.classList.remove('reveal-pending'); node.dataset.revealed = 'true'; });
      document.querySelectorAll('#hero-image, #preview-image').forEach(image => image.getAnimations().forEach(animation => animation.cancel()));
    }
    resetPointer(); updateScroll(); onChange();
  }
  toggle.addEventListener('click', () => {
    preference = !preference;
    try { localStorage.setItem('zaowu-site-motion', preference ? 'on' : 'off'); } catch {}
    refresh();
  });
  reduced.addEventListener('change', refresh);
  pointer.addEventListener('change', resetPointer);
  addEventListener('scroll', () => { if (!frame) frame = requestAnimationFrame(updateScroll); }, {passive:true});
  addEventListener('resize', () => { bounds = null; if (!frame) frame = requestAnimationFrame(updateScroll); }, {passive:true});
  showcase.addEventListener('pointerenter', () => { if (enabled && pointer.matches) bounds = showcase.getBoundingClientRect(); });
  showcase.addEventListener('pointermove', event => {
    if (!enabled || !pointer.matches || pointerFrame) return;
    const x = event.clientX, y = event.clientY;
    pointerFrame = requestAnimationFrame(() => {
      pointerFrame = 0;
      bounds ||= showcase.getBoundingClientRect();
      const px = Math.min(1,Math.max(0,(x - bounds.left) / bounds.width)), py = Math.min(1,Math.max(0,(y - bounds.top) / bounds.height));
      showcase.style.setProperty('--tilt-x', (-(py - .5) * 2.4) + 'deg');
      showcase.style.setProperty('--tilt-y', ((px - .5) * 3.2) + 'deg');
      showcase.style.setProperty('--light-x', px * 100 + '%'); showcase.style.setProperty('--light-y', py * 100 + '%'); showcase.style.setProperty('--light-on', '1');
    });
  });
  showcase.addEventListener('pointerleave', resetPointer);
  document.addEventListener('focusin', event => {
    const node = event.target.closest('.reveal-pending');
    if (node) { node.classList.remove('reveal-pending'); node.dataset.revealed = 'true'; revealObserver?.unobserve(node); }
  });
  if (typeof IntersectionObserver !== 'undefined') {
    const links = [...document.querySelectorAll('.site-header nav a')];
    const sections = new IntersectionObserver(entries => entries.forEach(entry => {
      if (entry.isIntersecting) links.forEach(link => { if (link.hash === '#' + entry.target.id) link.setAttribute('aria-current','location'); else link.removeAttribute('aria-current'); });
    }), {rootMargin:'-15% 0px -50% 0px'});
    links.forEach(link => sections.observe(document.querySelector(link.hash)));
  }
  refresh();
}
