<script setup>
import { onBeforeUnmount, onMounted, ref } from 'vue'
import BioDecor from '../components/BioDecor.vue'

const emit = defineEmits(['start'])
const canvasRef = ref(null)
let rafId = 0
let cleanupResize = null
let lastWheelAt = 0

const start = () => emit('start')

const onWheel = (event) => {
  if (event.deltaY < 18) return
  const now = Date.now()
  if (now - lastWheelAt < 900) return
  lastWheelAt = now
  start()
}

onMounted(() => {
  const canvas = canvasRef.value
  const ctx = canvas?.getContext('2d')
  if (!canvas || !ctx) return

  const particles = Array.from({ length: 84 }, (_, i) => ({
    x: Math.random(),
    y: Math.random(),
    r: 1.2 + Math.random() * 3.8,
    speed: 0.18 + Math.random() * 0.36,
    phase: Math.random() * Math.PI * 2,
    hue: i % 3,
  }))

  const resize = () => {
    const dpr = Math.min(window.devicePixelRatio || 1, 2)
    canvas.width = Math.floor(canvas.clientWidth * dpr)
    canvas.height = Math.floor(canvas.clientHeight * dpr)
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }

  const drawRibbon = (time, offset, color, alpha, width) => {
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    ctx.beginPath()
    for (let x = -80; x <= w + 80; x += 18) {
      const t = x / w
      const y =
        h * (0.34 + offset) +
        Math.sin(t * 7.2 + time * 0.00075 + offset * 8) * 44 +
        Math.cos(t * 13.5 - time * 0.00042) * 18
      if (x === -80) ctx.moveTo(x, y)
      else ctx.lineTo(x, y)
    }
    ctx.strokeStyle = color
    ctx.globalAlpha = alpha
    ctx.lineWidth = width
    ctx.lineCap = 'round'
    ctx.stroke()
  }

  const tick = (time) => {
    const w = canvas.clientWidth
    const h = canvas.clientHeight
    ctx.clearRect(0, 0, w, h)

    const bg = ctx.createLinearGradient(0, 0, w, h)
    bg.addColorStop(0, '#ffffff')
    bg.addColorStop(0.55, '#fbfdfb')
    bg.addColorStop(1, '#f4f8f6')
    ctx.fillStyle = bg
    ctx.fillRect(0, 0, w, h)

    drawRibbon(time, -0.1, '#dfeee7', 0.82, 42)
    drawRibbon(time, 0.07, '#edf6f1', 0.95, 64)
    drawRibbon(time, 0.22, '#d8e8e1', 0.54, 28)

    particles.forEach((p, index) => {
      const drift = Math.sin(time * 0.00055 + p.phase) * 0.026
      p.y -= p.speed / h
      p.x += drift / w
      if (p.y < -0.08) {
        p.y = 1.08
        p.x = Math.random()
      }
      const x = ((p.x + 1) % 1) * w
      const y = p.y * h
      ctx.beginPath()
      ctx.fillStyle = p.hue === 0 ? '#dbeae2' : p.hue === 1 ? '#e8f1ec' : '#d4e7df'
      ctx.globalAlpha = 0.32 + Math.sin(time * 0.001 + index) * 0.08
      ctx.arc(x, y, p.r, 0, Math.PI * 2)
      ctx.fill()
    })

    ctx.globalAlpha = 1
    rafId = requestAnimationFrame(tick)
  }

  resize()
  window.addEventListener('resize', resize)
  cleanupResize = () => window.removeEventListener('resize', resize)
  rafId = requestAnimationFrame(tick)
})

onBeforeUnmount(() => {
  if (rafId) cancelAnimationFrame(rafId)
  cleanupResize?.()
})
</script>

<template>
  <section class="landing-scene" @wheel.passive="onWheel">
    <canvas ref="canvasRef" class="landing-flow" aria-hidden="true"></canvas>

    <header class="landing-topbar">
      <div class="brand-lockup">
        <div class="brand-mark">K</div>
        <div>
          <div class="brand-name">KnowLab</div>
          <div class="brand-caption">医学与生物教材知识整合</div>
        </div>
      </div>
      <div class="topbar-meta">
        <span>双 Agent 抽取与融合</span>
        <span>RAG 溯源问答</span>
      </div>
    </header>

    <BioDecor
      kind="dna"
      :size="420"
      color="#7aa391"
      extraClass="absolute -left-24 top-24 opacity-[0.10] drift-slow"
    />
    <BioDecor
      kind="cell"
      :size="520"
      color="#95b6a6"
      extraClass="absolute -right-32 top-8 opacity-[0.09] spin-slow"
    />
    <BioDecor
      kind="mol"
      :size="220"
      color="#6f9e8c"
      extraClass="absolute right-20 bottom-20 opacity-[0.13] drift"
    />

    <main class="landing-content">
      <div class="landing-kicker">
        <span class="status-dot"></span>
        多教材理解 · 知识图谱 · 医学 RAG
      </div>

      <h1 class="landing-title">
        把分散教材整理成
        <span>可追溯的学习知识网络</span>
      </h1>

      <p class="landing-copy">
        面向医学与生物学习场景，上传教材后自动解析章节、抽取概念关系、融合重复知识点，并在对话中保留来源证据。
      </p>

      <div class="landing-actions">
        <button class="btn-primary btn-large" @click="start">
          进入工作台
          <svg viewBox="0 0 24 24" aria-hidden="true">
            <path d="M5 12h14M13 5l7 7-7 7" />
          </svg>
        </button>
        <button class="btn-quiet" @click="start">向下滑动也可进入</button>
      </div>
    </main>

    <div class="landing-preview" aria-hidden="true">
      <div class="preview-card source-mini">
        <span class="mini-label">Sources</span>
        <strong>神经生理学</strong>
        <small>32 章 · 1840 chunks</small>
      </div>
      <div class="preview-card chat-mini">
        <span class="mini-label">RAG</span>
        <p>动作电位的触发机制是什么？</p>
      </div>
      <div class="preview-card graph-mini">
        <span></span><span></span><span></span><i></i><i></i>
      </div>
    </div>

    <div class="scroll-cue">
      <span></span>
      滑动进入
    </div>
  </section>
</template>
