<template>
  <div class="infographic-dashboard">
    <!-- Section Title -->
    <div class="infographic-header">
      <span class="infographic-badge">Analytics</span>
      <span class="infographic-title">Simulation Overview</span>
    </div>

    <!-- Key Metrics Cards -->
    <div class="metrics-row">
      <div class="metric-card" v-for="card in metricCards" :key="card.label">
        <span class="metric-value">{{ card.value }}</span>
        <span class="metric-label">{{ card.label }}</span>
      </div>
    </div>

    <!-- Two-column: Action Distribution + Sentiment -->
    <div class="charts-row">
      <!-- Action Distribution -->
      <div class="chart-block">
        <div class="chart-title">Action Distribution</div>
        <div class="bar-chart">
          <div
            v-for="(bar, idx) in actionBars"
            :key="idx"
            class="bar-row"
          >
            <span class="bar-label">{{ bar.label }}</span>
            <div class="bar-track">
              <div class="bar-fill bar-twitter" :style="{ width: bar.twitterPct + '%' }"></div>
              <div class="bar-fill bar-reddit" :style="{ width: bar.redditPct + '%', left: bar.twitterPct + '%' }"></div>
            </div>
            <span class="bar-count">{{ bar.total }}</span>
          </div>
        </div>
      </div>

      <!-- Sentiment Breakdown -->
      <div class="chart-block">
        <div class="chart-title">Sentiment Breakdown</div>
        <div class="sentiment-bars">
          <div class="sentiment-row" v-if="data.sentiment_breakdown">
            <div class="sentiment-item positive">
              <span class="sentiment-dot"></span>
              <span class="sentiment-label">Positive</span>
              <span class="sentiment-pct">{{ data.sentiment_breakdown.positive_ratio || 0 }}%</span>
            </div>
            <div class="sentiment-item neutral">
              <span class="sentiment-dot"></span>
              <span class="sentiment-label">Neutral</span>
              <span class="sentiment-pct">{{ data.sentiment_breakdown.neutral_ratio || 0 }}%</span>
            </div>
            <div class="sentiment-item negative">
              <span class="sentiment-dot"></span>
              <span class="sentiment-label">Negative</span>
              <span class="sentiment-pct">{{ data.sentiment_breakdown.negative_ratio || 0 }}%</span>
            </div>
          </div>
          <div class="sentiment-stacked">
            <div class="stacked-positive" :style="{ width: (data.sentiment_breakdown?.positive_ratio || 0) + '%' }"></div>
            <div class="stacked-neutral" :style="{ width: (data.sentiment_breakdown?.neutral_ratio || 0) + '%' }"></div>
            <div class="stacked-negative" :style="{ width: (data.sentiment_breakdown?.negative_ratio || 0) + '%' }"></div>
          </div>
        </div>

        <!-- Top Agents -->
        <div class="chart-title" style="margin-top: 16px;">Top Agents</div>
        <div class="agents-table">
          <div v-for="(agent, idx) in topAgents" :key="idx" class="agent-row">
            <span class="agent-rank">{{ idx + 1 }}</span>
            <span class="agent-name">{{ agent.agent_name }}</span>
            <span class="agent-stat">{{ agent.total_actions }} actions</span>
          </div>
        </div>
      </div>
    </div>

    <!-- Timeline Sparkline -->
    <div class="timeline-block" v-if="timeline.length > 0">
      <div class="chart-title">Activity Timeline (by Round)</div>
      <div class="sparkline">
        <div
          v-for="(round, idx) in timeline"
          :key="idx"
          class="spark-bar"
          :style="{ height: round.heightPct + '%' }"
          :title="`Round ${round.round_num}: ${round.total} actions`"
        >
          <span class="spark-label" v-if="idx === 0 || idx === timeline.length - 1">R{{ round.round_num }}</span>
        </div>
      </div>
    </div>
  </div>
</template>

<script setup>
import { computed } from 'vue'

const props = defineProps({
  data: {
    type: Object,
    required: true,
  },
})

const metricCards = computed(() => {
  const km = props.data.key_metrics || {}
  return [
    { label: 'Agents', value: km.total_agents ?? '-' },
    { label: 'Posts', value: km.total_posts ?? '-' },
    { label: 'Engagement', value: km.total_engagement ?? '-' },
    { label: 'Avg Activity', value: km.avg_activity ?? '-' },
    { label: 'Rounds', value: km.total_rounds ?? '-' },
  ]
})

const actionBars = computed(() => {
  const dist = props.data.action_distribution?.by_type || {}
  const byPlatform = props.data.action_distribution?.by_platform || {}
  const maxVal = Math.max(...Object.values(dist), 1)

  const labels = {
    CREATE_POST: 'Posts',
    LIKE_POST: 'Likes',
    CREATE_COMMENT: 'Comments',
    REPOST: 'Reposts',
    FOLLOW: 'Follows',
    DISLIKE_POST: 'Dislikes',
    QUOTE_POST: 'Quotes',
  }

  return Object.entries(dist)
    .filter(([k]) => labels[k])
    .sort((a, b) => b[1] - a[1])
    .slice(0, 6)
    .map(([type, total]) => {
      const tw = byPlatform.twitter?.[type] || 0
      const rd = byPlatform.reddit?.[type] || 0
      return {
        label: labels[type] || type,
        total,
        twitterPct: (tw / maxVal) * 100,
        redditPct: (rd / maxVal) * 100,
      }
    })
})

const topAgents = computed(() => {
  return (props.data.top_agents || []).slice(0, 5)
})

const timeline = computed(() => {
  const rounds = props.data.timeline || []
  if (rounds.length === 0) return []
  const maxActions = Math.max(...rounds.map(r => r.total), 1)
  return rounds.map(r => ({
    ...r,
    heightPct: Math.max((r.total / maxActions) * 100, 4),
  }))
})
</script>

<style scoped>
.infographic-dashboard {
  padding: 16px 24px;
  border-bottom: 1px solid #EAEAEA;
  background: #FAFAFA;
}

.infographic-header {
  display: flex;
  align-items: center;
  gap: 8px;
  margin-bottom: 14px;
}

.infographic-badge {
  font-size: 10px;
  font-weight: 700;
  text-transform: uppercase;
  letter-spacing: 0.5px;
  color: #666;
  background: #EEE;
  padding: 2px 8px;
  border-radius: 3px;
}

.infographic-title {
  font-size: 13px;
  font-weight: 700;
  color: #333;
}

/* Metrics Cards */
.metrics-row {
  display: flex;
  gap: 12px;
  margin-bottom: 16px;
}

.metric-card {
  flex: 1;
  background: #FFF;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 10px 12px;
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.metric-value {
  font-family: 'JetBrains Mono', monospace;
  font-size: 20px;
  font-weight: 800;
  color: #111;
}

.metric-label {
  font-size: 11px;
  font-weight: 600;
  color: #888;
  text-transform: uppercase;
  letter-spacing: 0.3px;
}

/* Charts Row */
.charts-row {
  display: flex;
  gap: 16px;
  margin-bottom: 16px;
}

.chart-block {
  flex: 1;
  background: #FFF;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 12px;
}

.chart-title {
  font-size: 11px;
  font-weight: 700;
  color: #666;
  text-transform: uppercase;
  letter-spacing: 0.3px;
  margin-bottom: 10px;
}

/* Bar Chart */
.bar-chart {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.bar-row {
  display: flex;
  align-items: center;
  gap: 8px;
}

.bar-label {
  font-size: 11px;
  font-weight: 600;
  color: #555;
  width: 70px;
  text-align: right;
  flex-shrink: 0;
}

.bar-track {
  flex: 1;
  height: 12px;
  background: #F0F0F0;
  border-radius: 3px;
  position: relative;
  overflow: hidden;
}

.bar-fill {
  position: absolute;
  top: 0;
  height: 100%;
  border-radius: 3px;
}

.bar-twitter {
  background: #1DA1F2;
  left: 0;
}

.bar-reddit {
  background: #FF4500;
  opacity: 0.7;
}

.bar-count {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 600;
  color: #555;
  width: 35px;
  flex-shrink: 0;
}

/* Sentiment */
.sentiment-bars {
  margin-bottom: 8px;
}

.sentiment-row {
  display: flex;
  gap: 12px;
  margin-bottom: 8px;
}

.sentiment-item {
  display: flex;
  align-items: center;
  gap: 4px;
  font-size: 11px;
  color: #555;
}

.sentiment-dot {
  width: 8px;
  height: 8px;
  border-radius: 50%;
  flex-shrink: 0;
}

.sentiment-item.positive .sentiment-dot { background: #4CAF50; }
.sentiment-item.neutral .sentiment-dot { background: #9E9E9E; }
.sentiment-item.negative .sentiment-dot { background: #F44336; }

.sentiment-pct {
  font-family: 'JetBrains Mono', monospace;
  font-weight: 700;
  font-size: 11px;
}

.sentiment-stacked {
  display: flex;
  height: 8px;
  border-radius: 4px;
  overflow: hidden;
  background: #F0F0F0;
}

.stacked-positive { background: #4CAF50; }
.stacked-neutral { background: #9E9E9E; }
.stacked-negative { background: #F44336; }

/* Agents Table */
.agents-table {
  display: flex;
  flex-direction: column;
  gap: 4px;
}

.agent-row {
  display: flex;
  align-items: center;
  gap: 8px;
  padding: 3px 0;
}

.agent-rank {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  font-weight: 700;
  color: #999;
  width: 18px;
  text-align: center;
}

.agent-name {
  font-size: 12px;
  font-weight: 600;
  color: #333;
  flex: 1;
  overflow: hidden;
  text-overflow: ellipsis;
  white-space: nowrap;
}

.agent-stat {
  font-family: 'JetBrains Mono', monospace;
  font-size: 11px;
  color: #888;
}

/* Timeline Sparkline */
.timeline-block {
  background: #FFF;
  border: 1px solid #E5E5E5;
  border-radius: 6px;
  padding: 12px;
}

.sparkline {
  display: flex;
  align-items: flex-end;
  gap: 3px;
  height: 50px;
}

.spark-bar {
  flex: 1;
  background: #1DA1F2;
  border-radius: 2px 2px 0 0;
  min-width: 4px;
  position: relative;
  transition: height 0.3s ease;
}

.spark-label {
  position: absolute;
  bottom: -16px;
  left: 50%;
  transform: translateX(-50%);
  font-size: 9px;
  font-family: 'JetBrains Mono', monospace;
  color: #999;
  white-space: nowrap;
}
</style>
