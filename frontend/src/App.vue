<script setup>
/**
 * 应用根：负责"层级切换"。
 *  view = 'landing'    初始欢迎层（医学装饰 + 主 CTA）
 *  view = 'workspace'  工作区（左侧历史 / 主区上传+对话 / 顶栏切图谱）
 *  view = 'graph'      知识图谱全屏
 */
import { ref, provide } from 'vue'
import LandingView from './views/LandingView.vue'
import WorkspaceView from './views/WorkspaceView.vue'
import GraphView from './views/GraphView.vue'

const view = ref('landing')
const goWorkspace = () => (view.value = 'workspace')
const goGraph = () => (view.value = 'graph')
const goLanding = () => (view.value = 'landing')

provide('nav', { goWorkspace, goGraph, goLanding })
</script>

<template>
  <div class="h-full w-full overflow-hidden">
    <transition name="scale-fade" mode="out-in">
      <LandingView v-if="view === 'landing'" key="landing" @start="goWorkspace" />
      <WorkspaceView
        v-else-if="view === 'workspace'"
        key="workspace"
        @open-graph="goGraph"
        @home="goLanding"
      />
      <GraphView v-else key="graph" @back="goWorkspace" />
    </transition>
  </div>
</template>
