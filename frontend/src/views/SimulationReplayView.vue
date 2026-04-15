<template>
  <div class="replay-view">
    <!-- Header -->
    <header class="replay-header">
      <div class="header-left">
        <button class="back-btn" @click="goBack">← {{ $t('common.back') }}</button>
        <div class="brand">
          <span class="brand-en">foresight</span>
          <span class="brand-sep">·</span>
          <span class="brand-zh">回放</span>
        </div>
      </div>
      <div class="header-center">
        <span class="sim-id mono">{{ simulationId }}</span>
        <span class="status-badge" :class="statusClass">{{ statusLabel }}</span>
      </div>
      <div class="header-right">
        <button class="icon-btn" @click="reload" :title="$t('common.refresh') || '刷新'">↻</button>
      </div>
    </header>

    <!-- Loading / Error -->
    <div v-if="loading" class="loading-screen">
      <div class="loading-text">加载回放数据…</div>
    </div>
    <div v-else-if="loadError" class="error-screen">
      <div class="error-text">加载失败: {{ loadError }}</div>
      <button class="primary-btn" @click="reload">重试</button>
    </div>

    <!-- Main 3-column layout -->
    <div v-else-if="replayData" class="replay-body">
      <!-- LEFT: Workflow timeline -->
      <aside class="col-workflow">
        <h3 class="col-title">工作流时间线</h3>
        <div class="workflow-list">
          <div
            v-for="step in replayData.workflow"
            :key="step.step"
            class="workflow-step"
            :class="{ 'is-completed': step.status === 'completed', 'is-running': step.status === 'running' }"
          >
            <div class="step-marker">
              <span class="step-num">{{ step.step }}</span>
            </div>
            <div class="step-body">
              <div class="step-name">{{ step.name }}</div>
              <div class="step-meta">
                <template v-if="step.step === 1">
                  <div class="meta-line">{{ step.metadata.files?.length || 0 }} 个文件 · {{ formatLength(step.metadata.text_length) }}</div>
                  <div class="meta-line dim" v-if="step.metadata.requirement">需求：{{ truncate(step.metadata.requirement, 40) }}</div>
                </template>
                <template v-else-if="step.step === 2">
                  <div class="meta-line">{{ step.metadata.entities_count }} 个实体</div>
                  <div class="meta-line dim mono">{{ step.metadata.graph_id }}</div>
                </template>
                <template v-else-if="step.step === 3">
                  <div class="meta-line">{{ step.metadata.profiles_count }} 个 Agent 人设</div>
                  <div class="meta-line dim">已加载 {{ step.metadata.agents_loaded }}</div>
                </template>
                <template v-else-if="step.step === 4">
                  <div class="meta-line">{{ step.metadata.total_simulation_hours }}h / 每轮 {{ step.metadata.minutes_per_round }}min</div>
                  <div class="meta-line dim">{{ step.metadata.initial_posts_count }} 条初始帖子</div>
                </template>
                <template v-else-if="step.step === 5">
                  <div class="meta-line">{{ step.metadata.total_rounds_executed }} 轮 · {{ step.metadata.total_actions }} 动作</div>
                  <div class="meta-line dim">
                    Twitter {{ step.metadata.by_platform?.twitter || 0 }} · Reddit {{ step.metadata.by_platform?.reddit || 0 }}
                  </div>
                </template>
              </div>
              <div class="step-status-tag" :class="step.status">{{ stepStatusLabel(step.status) }}</div>
            </div>
          </div>
        </div>
      </aside>

      <!-- CENTER: Featured action + scrolling feed -->
      <main class="col-center">
        <!-- Featured action card -->
        <section class="featured-action">
          <div class="featured-header">
            <span class="section-label">当前动作</span>
            <span v-if="currentAction" class="action-counter mono">
              {{ currentActionIndex + 1 }} / {{ allActions.length }}
            </span>
          </div>
          <div v-if="currentAction" class="action-card large">
            <div class="action-card-top">
              <div class="action-agent">
                <div class="agent-avatar">{{ agentInitial(currentAction.agent_name) }}</div>
                <div class="agent-info">
                  <div class="agent-name">{{ currentAction.agent_name }}</div>
                  <div class="agent-meta mono">#{{ currentAction.agent_id }} · {{ getAgentProfession(currentAction.agent_id) }}</div>
                </div>
              </div>
              <div class="action-tags">
                <span class="tag platform" :class="currentAction.platform">{{ currentAction.platform }}</span>
                <span class="tag action-type">{{ currentAction.action_type }}</span>
              </div>
            </div>
            <div class="action-content">
              {{ currentAction.action_args?.content || currentAction.action_args?.text || JSON.stringify(currentAction.action_args) }}
            </div>
            <div class="action-card-bottom">
              <span class="time-info">
                Day {{ currentRound?.simulated_day || '-' }} · {{ String(currentRound?.simulated_hour ?? 0).padStart(2, '0') }}:00
              </span>
              <span class="time-info mono dim">round {{ currentAction.round_num }}</span>
            </div>
          </div>
          <div v-else class="empty-card">
            <span>还没有动作可回放</span>
          </div>
        </section>

        <!-- Action feed -->
        <section class="feed-section">
          <div class="feed-header">
            <span class="section-label">动作流</span>
            <span class="dim mono">{{ visibleFeed.length }} / {{ allActions.length }}</span>
          </div>
          <div class="feed-list" ref="feedListRef">
            <div
              v-for="(action, idx) in visibleFeed"
              :key="idx"
              class="feed-row"
              :class="{ active: idx === visibleFeed.length - 1 }"
              @click="jumpToActionByGlobalIndex(action._gIdx)"
            >
              <span class="feed-time mono">r{{ action.round_num }}</span>
              <span class="feed-platform" :class="action.platform">{{ action.platform[0].toUpperCase() }}</span>
              <span class="feed-agent">{{ action.agent_name }}</span>
              <span class="feed-type">{{ action.action_type }}</span>
              <span class="feed-content">{{ truncate(action.action_args?.content || '', 60) }}</span>
            </div>
            <div v-if="visibleFeed.length === 0" class="feed-empty">尚无动作记录</div>
          </div>
        </section>
      </main>

      <!-- RIGHT: Aggregate stats -->
      <aside class="col-stats">
        <h3 class="col-title">全局统计</h3>

        <div class="stat-block">
          <div class="stat-row">
            <span class="stat-label">总动作</span>
            <span class="stat-value mono">{{ replayData.aggregate.total_actions }}</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">已跑 rounds</span>
            <span class="stat-value mono">{{ replayData.aggregate.rounds_with_actions }}</span>
          </div>
          <div class="stat-row">
            <span class="stat-label">Agent 总数</span>
            <span class="stat-value mono">{{ replayData.agents.length }}</span>
          </div>
        </div>

        <div class="stat-section">
          <div class="section-label-sm">类型分布</div>
          <div v-for="(count, type) in replayData.aggregate.action_type_distribution" :key="type" class="bar-row">
            <span class="bar-label">{{ type }}</span>
            <div class="bar-track">
              <div class="bar-fill" :style="{ width: barWidth(count) + '%' }"></div>
            </div>
            <span class="bar-num mono">{{ count }}</span>
          </div>
        </div>

        <div class="stat-section">
          <div class="section-label-sm">Top Agents</div>
          <div v-for="agent in replayData.aggregate.top_agents.slice(0, 8)" :key="agent.agent_id" class="top-agent-row">
            <span class="top-agent-rank mono">#{{ agent.agent_id }}</span>
            <span class="top-agent-name">{{ agent.agent_name }}</span>
            <span class="top-agent-count mono">{{ agent.count }}</span>
          </div>
        </div>

        <div class="stat-section">
          <div class="section-label-sm">平台分布</div>
          <div class="platform-split">
            <div class="platform-item twitter">
              <span class="platform-name">Twitter</span>
              <span class="platform-count mono">{{ replayData.aggregate.platform_totals?.twitter || 0 }}</span>
            </div>
            <div class="platform-item reddit">
              <span class="platform-name">Reddit</span>
              <span class="platform-count mono">{{ replayData.aggregate.platform_totals?.reddit || 0 }}</span>
            </div>
          </div>
        </div>
      </aside>
    </div>

    <!-- Bottom scrubber -->
    <footer v-if="replayData && allActions.length > 0" class="replay-footer">
      <div class="footer-controls">
        <button class="ctrl-btn" @click="stepBack" :disabled="currentActionIndex === 0">⏮</button>
        <button class="ctrl-btn primary" @click="togglePlay">
          {{ isPlaying ? '⏸' : '▶' }}
        </button>
        <button class="ctrl-btn" @click="stepForward" :disabled="currentActionIndex >= allActions.length - 1">⏭</button>
      </div>

      <div class="scrubber">
        <input
          type="range"
          min="0"
          :max="allActions.length - 1"
          v-model.number="currentActionIndex"
          @input="onScrubberInput"
        />
        <div class="scrubber-info">
          <span class="info-left mono">
            {{ currentActionIndex + 1 }} / {{ allActions.length }}
            · round {{ currentAction?.round_num ?? '-' }}/{{ replayData.config?.time_config?.total_simulation_hours
              ? Math.floor((replayData.config.time_config.total_simulation_hours * 60) / replayData.config.time_config.minutes_per_round)
              : '?' }}
          </span>
          <span class="info-right">
            Day {{ currentRound?.simulated_day || '-' }} ·
            {{ String(currentRound?.simulated_hour ?? 0).padStart(2, '0') }}:00
          </span>
        </div>
      </div>

      <div class="footer-speed">
        <span class="speed-label">速度</span>
        <button
          v-for="s in [0.5, 1, 2, 5, 10]"
          :key="s"
          class="speed-btn"
          :class="{ active: speed === s }"
          @click="speed = s"
        >{{ s }}x</button>
      </div>
    </footer>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted, nextTick, watch } from 'vue'
import { useRoute, useRouter } from 'vue-router'
import { getSimulationReplay } from '../api/simulation'

const route = useRoute()
const router = useRouter()
const simulationId = route.params.simulationId

const loading = ref(true)
const loadError = ref(null)
const replayData = ref(null)
const currentActionIndex = ref(0)
const isPlaying = ref(false)
const speed = ref(1)
const feedListRef = ref(null)

let playTimer = null

// All actions flattened in time order, each carrying its global index
const allActions = computed(() => {
  if (!replayData.value) return []
  const out = []
  let g = 0
  for (const round of replayData.value.rounds) {
    for (const action of round.actions) {
      out.push({ ...action, _gIdx: g, _round: round })
      g++
    }
  }
  return out
})

const currentAction = computed(() => allActions.value[currentActionIndex.value] || null)
const currentRound = computed(() => currentAction.value?._round || null)

const visibleFeed = computed(() => {
  // Show last 30 actions up to current
  const end = currentActionIndex.value + 1
  const start = Math.max(0, end - 30)
  return allActions.value.slice(start, end)
})

const statusClass = computed(() => {
  const s = replayData.value?.simulation?.status
  if (s === 'running') return 'running'
  if (s === 'completed' || s === 'ready') return 'completed'
  if (s === 'failed') return 'failed'
  return ''
})
const statusLabel = computed(() => {
  const s = replayData.value?.simulation?.status || '-'
  return ({ running: '运行中', completed: '已完成', ready: '就绪', failed: '失败', preparing: '准备中' })[s] || s
})

const maxTypeCount = computed(() => {
  const dist = replayData.value?.aggregate?.action_type_distribution || {}
  return Math.max(1, ...Object.values(dist))
})

function barWidth(count) {
  return Math.round((count / maxTypeCount.value) * 100)
}

function stepStatusLabel(s) {
  return ({ completed: '✓', running: '运行中', pending: '待开始', failed: '失败', ready: '就绪' })[s] || s
}

function truncate(s, n) {
  if (!s) return ''
  return s.length > n ? s.slice(0, n) + '…' : s
}

function formatLength(n) {
  if (!n) return '0 字符'
  if (n > 10000) return (n / 10000).toFixed(1) + 'w 字'
  if (n > 1000) return (n / 1000).toFixed(1) + 'k 字'
  return n + ' 字'
}

function agentInitial(name) {
  if (!name) return '?'
  return name.slice(0, 1).toUpperCase()
}

function getAgentProfession(agentId) {
  const a = replayData.value?.agents?.find(x => x.id === agentId)
  return a?.profession || '-'
}

async function loadReplay() {
  loading.value = true
  loadError.value = null
  try {
    const res = await getSimulationReplay(simulationId)
    if (res.success) {
      replayData.value = res.data
      // Reset to last action so user sees the most recent state
      const total = res.data.rounds.reduce((sum, r) => sum + r.actions.length, 0)
      currentActionIndex.value = Math.max(0, total - 1)
    } else {
      loadError.value = res.error || '未知错误'
    }
  } catch (e) {
    loadError.value = e.message || String(e)
  } finally {
    loading.value = false
  }
}

function reload() {
  pause()
  loadReplay()
}

function togglePlay() {
  if (isPlaying.value) pause()
  else play()
}

function play() {
  if (currentActionIndex.value >= allActions.value.length - 1) {
    currentActionIndex.value = 0
  }
  isPlaying.value = true
  scheduleNextStep()
}

function pause() {
  isPlaying.value = false
  if (playTimer) {
    clearTimeout(playTimer)
    playTimer = null
  }
}

function scheduleNextStep() {
  if (!isPlaying.value) return
  const intervalMs = 800 / speed.value
  playTimer = setTimeout(() => {
    if (currentActionIndex.value < allActions.value.length - 1) {
      currentActionIndex.value++
      scrollFeedToBottom()
      scheduleNextStep()
    } else {
      pause()
    }
  }, intervalMs)
}

function stepForward() {
  pause()
  if (currentActionIndex.value < allActions.value.length - 1) {
    currentActionIndex.value++
    scrollFeedToBottom()
  }
}

function stepBack() {
  pause()
  if (currentActionIndex.value > 0) {
    currentActionIndex.value--
    scrollFeedToBottom()
  }
}

function onScrubberInput() {
  pause()
  scrollFeedToBottom()
}

function jumpToActionByGlobalIndex(idx) {
  pause()
  currentActionIndex.value = idx
}

function scrollFeedToBottom() {
  nextTick(() => {
    if (feedListRef.value) {
      feedListRef.value.scrollTop = feedListRef.value.scrollHeight
    }
  })
}

function goBack() {
  router.back()
}

watch(speed, () => {
  if (isPlaying.value) {
    if (playTimer) clearTimeout(playTimer)
    scheduleNextStep()
  }
})

onMounted(() => {
  loadReplay()
})

onUnmounted(() => {
  pause()
})
</script>

<style scoped>
.replay-view {
  height: 100vh;
  display: flex;
  flex-direction: column;
  background: #FAFAFA;
  font-family: 'Space Grotesk', 'Noto Sans SC', system-ui, sans-serif;
  color: #1A1A1A;
  overflow: hidden;
}

.mono { font-family: 'JetBrains Mono', monospace; }
.dim { color: #999; }

/* ========== Header ========== */
.replay-header {
  height: 56px;
  background: #FFF;
  border-bottom: 1px solid #E5E5E5;
  display: flex;
  align-items: center;
  padding: 0 24px;
  flex-shrink: 0;
}
.header-left { display: flex; align-items: center; gap: 16px; flex: 1; }
.header-center { display: flex; align-items: center; gap: 12px; flex: 1; justify-content: center; }
.header-right { flex: 1; display: flex; justify-content: flex-end; gap: 8px; }

.back-btn {
  background: transparent;
  border: 1px solid #E5E5E5;
  padding: 6px 12px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
  color: #666;
  transition: all 0.15s;
}
.back-btn:hover { background: #F5F5F5; color: #000; }

.brand { display: flex; align-items: baseline; gap: 6px; font-weight: 600; }
.brand-en { font-size: 14px; letter-spacing: 0.5px; }
.brand-sep { color: #CCC; }
.brand-zh { font-size: 13px; }

.sim-id { font-size: 11px; color: #666; padding: 4px 8px; background: #F5F5F5; border-radius: 4px; }

.status-badge {
  font-size: 10px;
  font-weight: 600;
  padding: 4px 10px;
  border-radius: 4px;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  background: #F5F5F5;
  color: #999;
}
.status-badge.running { background: #FFF3E0; color: #FF5722; }
.status-badge.completed { background: #E8F5E9; color: #2E7D32; }
.status-badge.failed { background: #FFEBEE; color: #C62828; }

.icon-btn {
  background: transparent;
  border: 1px solid #E5E5E5;
  width: 32px;
  height: 32px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 16px;
  color: #666;
}
.icon-btn:hover { background: #F5F5F5; color: #000; }

/* ========== Loading / Error ========== */
.loading-screen, .error-screen {
  flex: 1;
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 16px;
}
.loading-text, .error-text { color: #666; font-size: 14px; }

.primary-btn {
  background: #1A1A1A;
  color: #FFF;
  border: none;
  padding: 8px 20px;
  border-radius: 4px;
  cursor: pointer;
  font-size: 12px;
}

/* ========== Body 3-col layout ========== */
.replay-body {
  flex: 1;
  display: grid;
  grid-template-columns: 280px 1fr 280px;
  gap: 1px;
  background: #E5E5E5;
  overflow: hidden;
}

.col-workflow, .col-stats {
  background: #FFF;
  padding: 20px 16px;
  overflow-y: auto;
}

.col-center {
  background: #FFF;
  padding: 20px 24px;
  display: flex;
  flex-direction: column;
  gap: 20px;
  overflow: hidden;
}

.col-title {
  font-size: 11px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #999;
  margin: 0 0 16px 0;
}

/* ========== Workflow ========== */
.workflow-list { display: flex; flex-direction: column; gap: 4px; position: relative; }

.workflow-step {
  display: flex;
  gap: 12px;
  padding: 12px 0;
  position: relative;
}
.workflow-step:not(:last-child)::before {
  content: '';
  position: absolute;
  left: 13px;
  top: 36px;
  bottom: -4px;
  width: 1px;
  background: #E5E5E5;
}

.step-marker {
  width: 28px;
  height: 28px;
  border-radius: 50%;
  background: #F5F5F5;
  display: flex;
  align-items: center;
  justify-content: center;
  flex-shrink: 0;
  border: 1px solid #E0E0E0;
  z-index: 1;
}
.workflow-step.is-completed .step-marker { background: #E8F5E9; border-color: #4CAF50; }
.workflow-step.is-running .step-marker { background: #FFF3E0; border-color: #FF5722; animation: pulse-border 1.5s infinite; }

.step-num { font-size: 11px; font-weight: 700; color: #666; }
.workflow-step.is-completed .step-num { color: #2E7D32; }
.workflow-step.is-running .step-num { color: #FF5722; }

.step-body { flex: 1; min-width: 0; }
.step-name { font-size: 13px; font-weight: 600; margin-bottom: 4px; }
.step-meta { font-size: 11px; color: #666; line-height: 1.5; }
.meta-line { white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }

.step-status-tag {
  display: inline-block;
  font-size: 10px;
  padding: 2px 6px;
  border-radius: 3px;
  margin-top: 4px;
  background: #F5F5F5;
  color: #999;
}
.step-status-tag.completed { background: #E8F5E9; color: #2E7D32; }
.step-status-tag.running { background: #FFF3E0; color: #FF5722; }
.step-status-tag.failed { background: #FFEBEE; color: #C62828; }

@keyframes pulse-border {
  0%, 100% { box-shadow: 0 0 0 0 rgba(255, 87, 34, 0.4); }
  50% { box-shadow: 0 0 0 4px rgba(255, 87, 34, 0); }
}

/* ========== Featured action ========== */
.featured-action { display: flex; flex-direction: column; gap: 12px; flex-shrink: 0; }
.featured-header { display: flex; justify-content: space-between; align-items: baseline; }
.section-label { font-size: 11px; font-weight: 700; text-transform: uppercase; letter-spacing: 1px; color: #999; }
.action-counter { font-size: 11px; color: #666; }

.action-card.large {
  background: #FFF;
  border: 1px solid #E5E5E5;
  border-radius: 8px;
  padding: 20px;
  box-shadow: 0 2px 8px rgba(0, 0, 0, 0.04);
}

.action-card-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 14px; }
.action-agent { display: flex; gap: 12px; align-items: center; }
.agent-avatar {
  width: 40px;
  height: 40px;
  border-radius: 50%;
  background: linear-gradient(135deg, #FF5722, #FF8A65);
  color: #FFF;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 16px;
}
.agent-name { font-size: 14px; font-weight: 600; }
.agent-meta { font-size: 11px; color: #999; margin-top: 2px; }

.action-tags { display: flex; gap: 6px; }
.tag {
  font-size: 10px;
  padding: 3px 8px;
  border-radius: 3px;
  font-weight: 600;
  text-transform: uppercase;
}
.tag.platform.twitter { background: #E1F5FE; color: #0277BD; }
.tag.platform.reddit { background: #FFEBEE; color: #C62828; }
.tag.action-type { background: #F5F5F5; color: #666; }

.action-content {
  font-size: 14px;
  line-height: 1.6;
  color: #1A1A1A;
  padding: 12px 0;
  border-top: 1px solid #F0F0F0;
  border-bottom: 1px solid #F0F0F0;
  margin-bottom: 12px;
  max-height: 120px;
  overflow-y: auto;
}

.action-card-bottom { display: flex; justify-content: space-between; font-size: 11px; color: #666; }
.time-info { display: flex; align-items: center; gap: 4px; }

.empty-card {
  background: #F9F9F9;
  border: 1px dashed #E0E0E0;
  border-radius: 8px;
  padding: 40px;
  text-align: center;
  color: #999;
  font-size: 13px;
}

/* ========== Feed ========== */
.feed-section { flex: 1; display: flex; flex-direction: column; gap: 8px; min-height: 0; }
.feed-header { display: flex; justify-content: space-between; align-items: baseline; }

.feed-list {
  flex: 1;
  background: #FAFAFA;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  overflow-y: auto;
  padding: 4px;
  min-height: 0;
}

.feed-row {
  display: grid;
  grid-template-columns: 36px 20px 100px 110px 1fr;
  gap: 8px;
  padding: 6px 8px;
  font-size: 11px;
  cursor: pointer;
  border-radius: 3px;
  align-items: center;
  border-left: 2px solid transparent;
}
.feed-row:hover { background: #F0F0F0; }
.feed-row.active {
  background: #FFF3E0;
  border-left-color: #FF5722;
}

.feed-time { color: #999; font-family: 'JetBrains Mono', monospace; }
.feed-platform {
  width: 18px;
  height: 18px;
  border-radius: 3px;
  display: flex;
  align-items: center;
  justify-content: center;
  font-weight: 700;
  font-size: 10px;
}
.feed-platform.twitter { background: #E1F5FE; color: #0277BD; }
.feed-platform.reddit { background: #FFEBEE; color: #C62828; }

.feed-agent { font-weight: 600; color: #1A1A1A; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.feed-type { color: #666; font-size: 10px; }
.feed-content { color: #555; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }

.feed-empty { text-align: center; color: #BBB; padding: 40px; font-size: 12px; }

/* ========== Stats column ========== */
.stat-block {
  display: flex;
  flex-direction: column;
  gap: 8px;
  padding: 12px;
  background: #FAFAFA;
  border-radius: 6px;
  margin-bottom: 20px;
}
.stat-row { display: flex; justify-content: space-between; align-items: center; }
.stat-label { font-size: 12px; color: #666; }
.stat-value { font-size: 14px; font-weight: 700; }

.stat-section { margin-bottom: 24px; }
.section-label-sm {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 1px;
  color: #999;
  margin-bottom: 10px;
}

.bar-row { display: grid; grid-template-columns: 80px 1fr 32px; gap: 8px; align-items: center; padding: 4px 0; font-size: 11px; }
.bar-label { color: #666; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.bar-track { background: #F0F0F0; height: 6px; border-radius: 3px; overflow: hidden; }
.bar-fill { background: #FF5722; height: 100%; transition: width 0.3s; }
.bar-num { color: #1A1A1A; text-align: right; font-size: 11px; font-weight: 600; }

.top-agent-row {
  display: grid;
  grid-template-columns: 28px 1fr 32px;
  gap: 8px;
  padding: 5px 0;
  font-size: 11px;
  align-items: center;
}
.top-agent-rank { color: #999; }
.top-agent-name { color: #1A1A1A; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.top-agent-count { text-align: right; font-weight: 600; }

.platform-split { display: flex; gap: 8px; }
.platform-item {
  flex: 1;
  padding: 10px;
  border-radius: 6px;
  display: flex;
  flex-direction: column;
  align-items: center;
  gap: 4px;
}
.platform-item.twitter { background: #E1F5FE; color: #0277BD; }
.platform-item.reddit { background: #FFEBEE; color: #C62828; }
.platform-name { font-size: 10px; font-weight: 600; text-transform: uppercase; }
.platform-count { font-size: 18px; font-weight: 700; }

/* ========== Footer scrubber ========== */
.replay-footer {
  height: 72px;
  background: #FFF;
  border-top: 1px solid #E5E5E5;
  display: flex;
  align-items: center;
  padding: 0 24px;
  gap: 24px;
  flex-shrink: 0;
}

.footer-controls { display: flex; gap: 6px; align-items: center; }
.ctrl-btn {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  border: 1px solid #E0E0E0;
  background: #FFF;
  cursor: pointer;
  font-size: 14px;
  color: #666;
  display: flex;
  align-items: center;
  justify-content: center;
  transition: all 0.15s;
}
.ctrl-btn:hover:not(:disabled) { background: #F5F5F5; color: #000; }
.ctrl-btn:disabled { opacity: 0.4; cursor: not-allowed; }
.ctrl-btn.primary {
  background: #1A1A1A;
  color: #FFF;
  width: 44px;
  height: 44px;
  font-size: 16px;
  border-color: #1A1A1A;
}
.ctrl-btn.primary:hover:not(:disabled) { background: #333; }

.scrubber { flex: 1; display: flex; flex-direction: column; gap: 4px; }
.scrubber input[type="range"] {
  width: 100%;
  -webkit-appearance: none;
  appearance: none;
  background: transparent;
  height: 24px;
  margin: 0;
}
.scrubber input[type="range"]::-webkit-slider-runnable-track {
  height: 4px;
  background: #E5E5E5;
  border-radius: 2px;
}
.scrubber input[type="range"]::-webkit-slider-thumb {
  -webkit-appearance: none;
  appearance: none;
  width: 14px;
  height: 14px;
  background: #FF5722;
  border-radius: 50%;
  margin-top: -5px;
  cursor: pointer;
}
.scrubber input[type="range"]::-moz-range-thumb {
  width: 14px;
  height: 14px;
  background: #FF5722;
  border-radius: 50%;
  cursor: pointer;
  border: none;
}
.scrubber-info { display: flex; justify-content: space-between; font-size: 11px; }
.info-left { color: #666; }
.info-right { color: #1A1A1A; font-weight: 600; }

.footer-speed { display: flex; gap: 4px; align-items: center; }
.speed-label { font-size: 11px; color: #999; margin-right: 4px; }
.speed-btn {
  background: transparent;
  border: 1px solid #E5E5E5;
  padding: 4px 10px;
  border-radius: 3px;
  cursor: pointer;
  font-size: 11px;
  color: #666;
  font-family: 'JetBrains Mono', monospace;
}
.speed-btn:hover { background: #F5F5F5; }
.speed-btn.active { background: #1A1A1A; color: #FFF; border-color: #1A1A1A; }
</style>
