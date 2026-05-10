<script setup>
import BioDecor from '../components/BioDecor.vue'

const emit = defineEmits(['start'])
</script>

<template>
  <section class="relative h-full w-full bg-grid overflow-hidden">
    <!-- 顶栏 -->
    <header class="absolute top-0 left-0 right-0 px-10 py-5 flex items-center justify-between z-20">
      <div class="flex items-center gap-2.5">
        <div class="w-7 h-7 rounded-lg bg-gradient-to-br from-sky-500 to-teal-500 grid place-items-center text-white text-[11px] font-bold">K</div>
        <div class="font-semibold tracking-wide text-slate-800">KnowLab</div>
        <span class="tag ml-2">学科知识整合智能体</span>
      </div>
      <div class="text-xs text-slate-400 hidden md:block">浙大极速黑客松 · 双 Agent 工作流</div>
    </header>

    <!-- 装饰：DNA / 细胞 / 分子 -->
    <BioDecor kind="dna" :size="380" color="#0ea5e9"
              extraClass="absolute -left-16 top-24 opacity-[0.10] drift-slow" />
    <BioDecor kind="cell" :size="500" color="#14b8a6"
              extraClass="absolute -right-32 -top-10 opacity-[0.08] spin-slow" />
    <BioDecor kind="mol" :size="220" color="#0ea5e9"
              extraClass="absolute right-24 bottom-16 opacity-[0.13] drift" />
    <BioDecor kind="cell" :size="160" color="#0ea5e9"
              extraClass="absolute left-1/3 bottom-24 opacity-[0.10] drift-slow" />

    <!-- 主内容 -->
    <div class="relative z-10 h-full flex flex-col items-center justify-center px-8">
      <div class="max-w-3xl text-center">
        <div class="inline-flex items-center gap-2 px-3 py-1 rounded-full bg-white border border-slate-200 text-[12px] text-slate-500 mb-6 shadow-sm">
          <span class="w-1.5 h-1.5 rounded-full bg-emerald-500 animate-pulse"></span>
          双 Agent 协作 · Extractor + Aligner
        </div>

        <h1 class="text-[56px] leading-[1.1] font-semibold tracking-tight">
          把 <span class="gradient-text">7 本教材</span><br/>
          凝炼成一张可生长的<span class="gradient-text">知识图谱</span>。
        </h1>

        <p class="mt-6 text-slate-500 text-[15px] leading-relaxed max-w-xl mx-auto">
          上传多本医学/生物学教材，系统自动解析章节、抽取知识点、跨教材去重融合，
          并提供带原文溯源的 RAG 精准问答。
        </p>

        <div class="mt-10 flex items-center justify-center gap-3">
          <button class="btn-primary group inline-flex items-center gap-2"
                  @click="emit('start')">
            进入工作台
            <svg class="w-4 h-4 transition-transform group-hover:translate-x-0.5"
                 viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2"
                 stroke-linecap="round" stroke-linejoin="round">
              <path d="M5 12h14M13 5l7 7-7 7"/>
            </svg>
          </button>
          <a href="https://github.com" target="_blank" class="btn-ghost text-sm">查看源码</a>
        </div>

        <!-- 三个能力卡 -->
        <div class="mt-20 grid grid-cols-3 gap-4 max-w-3xl mx-auto">
          <div v-for="f in features" :key="f.t"
               class="card p-5 text-left hover:shadow-md transition-shadow">
            <div class="w-9 h-9 rounded-lg bg-sky-50 grid place-items-center text-sky-600 mb-3">
              <component :is="f.icon" />
            </div>
            <div class="text-sm font-semibold text-slate-800">{{ f.t }}</div>
            <div class="mt-1 text-xs text-slate-500 leading-relaxed">{{ f.d }}</div>
          </div>
        </div>
      </div>
    </div>

    <!-- 底部脚注 -->
    <div class="absolute bottom-5 left-0 right-0 text-center text-[11px] text-slate-400">
      ⚕ 医学/生物学教学场景 · 白色简约 · 多教材整合
    </div>
  </section>
</template>

<script>
import { h } from 'vue'
const Icon = (path) => () => h('svg', {
  width: 18, height: 18, viewBox: '0 0 24 24', fill: 'none',
  stroke: 'currentColor', 'stroke-width': 2,
  'stroke-linecap': 'round', 'stroke-linejoin': 'round',
}, [h('path', { d: path })])

export default {
  data() {
    return {
      features: [
        { t: '解析 · 章节级', d: 'PDF/MD/TXT/DOCX 自动识别章节与页码',
          icon: Icon('M14 2H6a2 2 0 0 0-2 2v16a2 2 0 0 0 2 2h12a2 2 0 0 0 2-2V8z M14 2v6h6 M16 13H8 M16 17H8 M10 9H8') },
        { t: '抽取 · Agent A', d: 'LLM 结构化输出节点 + 关系（JSON 严格约束）',
          icon: Icon('M21 16V8a2 2 0 0 0-1-1.73l-7-4a2 2 0 0 0-2 0l-7 4A2 2 0 0 0 3 8v8a2 2 0 0 0 1 1.73l7 4a2 2 0 0 0 2 0l7-4A2 2 0 0 0 21 16z M3.27 6.96L12 12.01l8.73-5.05 M12 22.08V12') },
        { t: '融合 · Agent B', d: '相似度初筛 + LLM 裁决 merge/keep/remove',
          icon: Icon('M22 11.08V12a10 10 0 1 1-5.93-9.14 M22 4L12 14.01l-3-3') },
      ],
    }
  },
}
</script>
