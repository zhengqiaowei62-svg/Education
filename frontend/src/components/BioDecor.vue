<!--
  医学/生物装饰：DNA 双螺旋、细胞、分子。极淡极简，仅作画面层次。
-->
<template>
  <svg
    :width="size"
    :height="size"
    viewBox="0 0 200 200"
    fill="none"
    xmlns="http://www.w3.org/2000/svg"
    :class="['select-none pointer-events-none', extraClass]"
  >
    <!-- DNA -->
    <g v-if="kind === 'dna'" :stroke="color" stroke-width="1.4" stroke-linecap="round">
      <path d="M60 10 C 140 50, 60 80, 140 120 C 60 160, 140 190, 60 200" fill="none" />
      <path d="M140 10 C 60 50, 140 80, 60 120 C 140 160, 60 190, 140 200" fill="none" />
      <line v-for="(y, i) in rungs" :key="i" :x1="rungX1(y)" :y1="y" :x2="rungX2(y)" :y2="y" />
    </g>

    <!-- 细胞 -->
    <g v-else-if="kind === 'cell'" :stroke="color" stroke-width="1.2" fill="none">
      <circle cx="100" cy="100" r="80" />
      <circle cx="100" cy="100" r="60" stroke-dasharray="2 4" />
      <circle cx="100" cy="100" r="22" :fill="color" fill-opacity=".08" />
      <circle cx="100" cy="100" r="8" :fill="color" fill-opacity=".25" />
      <circle cx="60" cy="80" r="6" />
      <circle cx="140" cy="120" r="5" />
      <circle cx="120" cy="60" r="4" />
      <circle cx="70" cy="135" r="5" />
    </g>

    <!-- 分子（六边形+连线）-->
    <g v-else-if="kind === 'mol'" :stroke="color" stroke-width="1.3" fill="none" stroke-linejoin="round">
      <polygon points="100,30 160,65 160,135 100,170 40,135 40,65" />
      <line x1="100" y1="30" x2="100" y2="170" />
      <line x1="40" y1="65" x2="160" y2="135" />
      <line x1="160" y1="65" x2="40" y2="135" />
      <circle cx="100" cy="30" r="4" :fill="color" />
      <circle cx="160" cy="65" r="4" :fill="color" />
      <circle cx="160" cy="135" r="4" :fill="color" />
      <circle cx="100" cy="170" r="4" :fill="color" />
      <circle cx="40" cy="135" r="4" :fill="color" />
      <circle cx="40" cy="65" r="4" :fill="color" />
    </g>
  </svg>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  kind: { type: String, default: 'dna' }, // dna | cell | mol
  size: { type: [Number, String], default: 120 },
  color: { type: String, default: '#6f9584' },
  extraClass: { type: String, default: '' },
})

// DNA 横档线（连接两条曲线的位置近似）
const rungs = [25, 50, 75, 100, 125, 150, 175]
const rungX1 = (y) => 60 + 80 * Math.sin((y / 200) * Math.PI * 2)
const rungX2 = (y) => 140 - 80 * Math.sin((y / 200) * Math.PI * 2)
</script>
