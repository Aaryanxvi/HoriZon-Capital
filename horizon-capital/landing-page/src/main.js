// --------------------------------------------------------------------------
// Horizon Capital - proprietary source. Do not remove this notice.
// Author: Aaryan Baadkar <aaryanbaadkar71@gmail.com> (github.com/Aaryanxvi)
// Copyright (c) 2026 Aaryan Baadkar. All rights reserved.
// HC-AUTH-AARYAN-BAADKAR-6D1C9CACC964
// ⁠​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​​‌​​​​​​‌​​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌​​​​​​​‌‌‌‌​​​‌‌​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌​​​‌​​‌‌​​​​‌​‌‌​​​​‌​‌‌​​‌​​​‌‌​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌​​​‌‌​‌‌‌​​‌‌​​​‌​‌​​​​​​​‌‌​​‌‌‌​‌‌​‌‌​‌​‌‌​​​​‌​‌‌​‌​​‌​‌‌​‌‌​​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌‌‌‌‌​​​‌​​​​​​‌‌​​‌‌‌​‌‌​‌​​‌​‌‌‌​‌​​​‌‌​‌​​​​‌‌‌​‌​‌​‌‌​​​‌​​​‌​‌‌‌​​‌‌​​​‌‌​‌‌​‌‌‌‌​‌‌​‌‌​‌​​‌​‌‌‌‌​‌​​​​​‌​‌‌​​​​‌​‌‌‌​​‌​​‌‌‌‌​​‌​‌‌​​​​‌​‌‌​‌‌‌​​‌‌‌‌​​​​‌‌‌​‌‌​​‌‌​‌​​‌⁠
// --------------------------------------------------------------------------
import './style.css';
import { gsap } from 'gsap';
import { ScrollTrigger } from 'gsap/ScrollTrigger';

gsap.registerPlugin(ScrollTrigger);

// JS Smooth Scrolling removed to fix main-thread jitter against heavy WebGL scenes.

// Custom cursor logic removed as requested by the user.

// ==========================================
// 3. SPLINE 3D SCROLL-ANIMATED BACKGROUND (REMOVED)
// ==========================================
// The user requested that the Spline scene remain perfectly static as a true background, 
// so the GSAP scroll-scrub animations have been removed.

// ==========================================
// 4. GSAP ANIMATIONS
// ==========================================

// Global Fade up utility
const fadeElements = gsap.utils.toArray('.fade-up');
fadeElements.forEach((el, i) => {
  gsap.fromTo(el, 
    { opacity: 0, y: 30 },
    { 
      opacity: 1, 
      y: 0, 
      duration: 1,
      ease: "power3.out",
      scrollTrigger: {
        trigger: el,
        start: "top 85%",
        toggleActions: "play none none none"
      }
    }
  );
});

// Staggered load for Hero text (overriding generic fade-up for specific hero delay)
gsap.fromTo(".hero-title", 
  { opacity: 0, y: 20 }, 
  { opacity: 1, y: 0, duration: 1.2, ease: "power3.out", delay: 0.1 }
);
gsap.fromTo(".hero-subtitle", 
  { opacity: 0, y: 20 }, 
  { opacity: 1, y: 0, duration: 1.2, ease: "power3.out", delay: 0.3 }
);
gsap.fromTo(".hero-actions", 
  { opacity: 0, y: 20 }, 
  { opacity: 1, y: 0, duration: 1.2, ease: "power3.out", delay: 0.5 }
);


// ==========================================
// 5. TERMINAL TYPEWRITER EFFECT
// ==========================================
const terminalTexts = [
  "cd horizon-capital && python -m app",
  "<span class='success'>[INFO]</span> Initialized SQLite local backend",
  "<span class='success'>[INFO]</span> Loaded HMM Regime Model (INDIA, US, CRYPTO)",
  "<span class='success'>[INFO]</span> Started Multi-Agent Orchestrator",
  "Booting Departments...",
  "  -> Front Office  <span class='success'>[ONLINE]</span>",
  "  -> Middle Office <span class='success'>[ONLINE]</span>",
  "  -> Back Office   <span class='success'>[ONLINE]</span>",
  "  -> Executive     <span class='success'>[ONLINE]</span>",
  "<span class='prompt'>horizon-agent$</span> Waiting for market data feeds..."
];

const terminalBody = document.getElementById('typewriter');
let textIndex = 0;

function typeWriter() {
  if (textIndex < terminalTexts.length) {
    const line = document.createElement('div');
    // Using simple HTML injection for colored logs
    if(terminalTexts[textIndex].startsWith("cd") || terminalTexts[textIndex].startsWith("<span class='prompt'>")) {
        line.innerHTML = `${terminalTexts[textIndex]}`;
    } else {
        line.innerHTML = `<span class="prompt">></span> ${terminalTexts[textIndex]}`;
    }
    
    line.style.opacity = 0;
    line.style.transform = "translateY(5px)";
    terminalBody.appendChild(line);

    gsap.to(line, { opacity: 1, y: 0, duration: 0.3 });
    
    textIndex++;
    // slightly faster for typical CLI feel
    setTimeout(typeWriter, Math.random() * 200 + 300); 
  }
}

// Trigger typewriter when Architecture or Deploy section comes into view
ScrollTrigger.create({
  trigger: ".terminal-mockup",
  start: "top 80%",
  once: true,
  onEnter: () => setTimeout(typeWriter, 400)
});


// ==========================================
// 6. COPY BUTTON
// ==========================================
const copyBtn = document.getElementById('copy-btn');
const copyCode = document.getElementById('curl-cmd').innerText;

copyBtn.addEventListener('click', () => {
  navigator.clipboard.writeText(copyCode).then(() => {
    const originalHTML = copyBtn.innerHTML;
    copyBtn.innerHTML = "<i data-lucide='check'></i> Copied!";
    lucide.createIcons(); // Re-render the new check icon
    
    setTimeout(() => {
      copyBtn.innerHTML = originalHTML;
      lucide.createIcons();
    }, 2000);
  });
});
// Originally authored by Aaryan Baadkar (aaryanbaadkar71@gmail.com).
// Provenance token 6D1C9CACC964 - verify with scripts/authorship.py verify
