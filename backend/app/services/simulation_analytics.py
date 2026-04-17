"""
Simulation Analytics Service
直接读取 actions.jsonl 提供模拟行为统计数据和真实 Agent 发言内容。
用于报告生成时获取具体数字和可引用的原文。

数据来源：SimulationRunner.get_all_actions() → actions.jsonl
"""

import json
import random
from typing import Dict, Any, List, Optional
from collections import Counter, defaultdict

from ..utils.logger import get_logger
from .simulation_runner import SimulationRunner

logger = get_logger('foresight.simulation_analytics')

# 简单的情感关键词列表（避免 LLM 依赖）
POSITIVE_KEYWORDS = {
    '好', '棒', '赞', '喜欢', '支持', '期待', '感谢', '满意', '优秀', '不错',
    '开心', '高兴', '推荐', '值得', '信任', '认同', '赞同', ' helpful', 'agree',
    'great', 'good', 'love', 'excellent', 'amazing', 'awesome', 'nice', 'best',
    'like', 'support', 'happy', 'thank', 'recommend', 'worth',
}

NEGATIVE_KEYWORDS = {
    '差', '烂', '坑', '骗', '垃圾', '失望', '不满', '退款', '投诉', '问题',
    '糟糕', '难过', '愤怒', '不推荐', '浪费', '后悔', '差评', '反感', 'bad',
    'terrible', 'worst', 'hate', 'awful', 'disappoint', 'waste', 'refund',
    'complaint', 'angry', 'frustrat', 'annoy', 'poor', 'fail', 'scam',
}

# 有文本内容的 action types（可提取引用）
CONTENT_ACTION_TYPES = {'CREATE_POST', 'CREATE_COMMENT', 'QUOTE_POST'}

# 互动类型的 action types
ENGAGEMENT_ACTION_TYPES = {'LIKE_POST', 'DISLIKE_POST', 'REPOST', 'LIKE_COMMENT', 'DISLIKE_COMMENT'}


class SimulationAnalyticsService:
    """
    模拟数据分析服务

    直接读取 actions.jsonl 提供统计数据，不经过 Graphiti 知识图谱。
    """

    def get_overview_stats(self, simulation_id: str) -> Dict[str, Any]:
        """
        模拟全局统计概览

        Returns:
            {
                total_agents, total_actions, total_rounds,
                twitter_posts, reddit_posts, total_posts,
                total_engagement, avg_activity_per_agent,
                action_type_counts: {action_type: count},
                platform_breakdown: {platform: count},
            }
        """
        actions = SimulationRunner.get_all_actions(simulation_id, limit=50000)
        if not actions:
            return self._empty_overview()

        agent_ids = set()
        rounds = set()
        action_type_counts = Counter()
        platform_counts = Counter()
        posts = 0
        engagement = 0

        for action in actions:
            agent_ids.add(action.agent_id)
            rounds.add(action.round_num)
            action_type_counts[action.action_type] += 1
            platform_counts[action.platform] += 1

            if action.action_type == 'CREATE_POST':
                posts += 1
            elif action.action_type in ENGAGEMENT_ACTION_TYPES:
                engagement += 1

        total_agents = len(agent_ids)
        total_actions = len(actions)

        return {
            'total_agents': total_agents,
            'total_actions': total_actions,
            'total_rounds': max(rounds) + 1 if rounds else 0,
            'total_posts': posts,
            'twitter_posts': sum(1 for a in actions if a.action_type == 'CREATE_POST' and a.platform == 'twitter'),
            'reddit_posts': sum(1 for a in actions if a.action_type == 'CREATE_POST' and a.platform == 'reddit'),
            'total_engagement': engagement,
            'avg_activity_per_agent': round(total_actions / max(total_agents, 1), 1),
            'action_type_counts': dict(action_type_counts),
            'platform_breakdown': dict(platform_counts),
        }

    def get_top_posts(
        self,
        simulation_id: str,
        n: int = 10,
    ) -> List[Dict[str, Any]]:
        """
        获取最活跃的帖子（按该帖获得的互动数排序）

        Returns:
            [{agent_name, content, platform, round_num, engagement_count}]
        """
        actions = SimulationRunner.get_all_actions(simulation_id, limit=50000)
        if not actions:
            return []

        # 1. 收集所有原创帖
        posts = {}
        for action in actions:
            if action.action_type == 'CREATE_POST':
                content = action.action_args.get('content', '')
                key = (action.agent_name, content[:100], action.platform)
                posts[key] = {
                    'agent_name': action.agent_name,
                    'content': content,
                    'platform': action.platform,
                    'round_num': action.round_num,
                    'engagement_count': 0,
                }

        # 2. 统计每个帖的互动（通过被引用的内容匹配）
        post_contents = {k: v['content'][:80] for k, v in posts.items()}
        for action in actions:
            if action.action_type in ('LIKE_POST', 'REPOST', 'CREATE_COMMENT', 'QUOTE_POST'):
                referenced = (
                    action.action_args.get('post_content', '')
                    or action.action_args.get('quoted_content', '')
                )
                if not referenced:
                    continue
                ref_prefix = referenced[:80]
                for key, pc in post_contents.items():
                    if ref_prefix and pc and (ref_prefix in pc or pc in ref_prefix):
                        posts[key]['engagement_count'] += 1
                        break

        # 3. 按互动量排序
        sorted_posts = sorted(posts.values(), key=lambda x: x['engagement_count'], reverse=True)
        return sorted_posts[:n]

    def get_agent_quotes(
        self,
        simulation_id: str,
        n_positive: int = 5,
        n_negative: int = 5,
        n_random: int = 5,
    ) -> Dict[str, List[Dict[str, Any]]]:
        """
        提取真实 Agent 发言摘录，按情感分类

        Returns:
            {
                positive: [{agent_name, quote, platform, action_type, round_num}],
                negative: [...],
                random: [...],
            }
        """
        actions = SimulationRunner.get_all_actions(simulation_id, limit=50000)
        if not actions:
            return {'positive': [], 'negative': [], 'random': []}

        # 提取有文本内容的 action
        content_actions = []
        for action in actions:
            if action.action_type not in CONTENT_ACTION_TYPES:
                continue
            content = action.action_args.get('content', '')
            if not content or len(content.strip()) < 10:
                continue
            content_actions.append({
                'agent_name': action.agent_name,
                'quote': content.strip(),
                'platform': action.platform,
                'action_type': action.action_type,
                'round_num': action.round_num,
            })

        if not content_actions:
            return {'positive': [], 'negative': [], 'random': []}

        # 按情感分类
        positive = []
        negative = []
        neutral = []

        for item in content_actions:
            text_lower = item['quote'].lower()
            pos_score = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
            neg_score = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)

            if pos_score > neg_score:
                positive.append(item)
            elif neg_score > pos_score:
                negative.append(item)
            else:
                neutral.append(item)

        # 采样
        result = {
            'positive': self._deduplicate_and_sample(positive, n_positive),
            'negative': self._deduplicate_and_sample(negative, n_negative),
            'random': self._deduplicate_and_sample(
                neutral if neutral else content_actions, n_random
            ),
        }
        return result

    def get_action_distribution(self, simulation_id: str) -> Dict[str, Any]:
        """
        按类型/平台/轮次的动作分布

        Returns:
            {
                by_type: {action_type: count},
                by_platform: {platform: {action_type: count}},
                by_round: [{round_num, twitter, reddit, total}],
            }
        """
        actions = SimulationRunner.get_all_actions(simulation_id, limit=50000)
        if not actions:
            return {'by_type': {}, 'by_platform': {}, 'by_round': []}

        by_type = Counter()
        by_platform: Dict[str, Counter] = defaultdict(Counter)
        round_data: Dict[int, Dict] = {}

        for action in actions:
            by_type[action.action_type] += 1
            by_platform[action.platform][action.action_type] += 1

            r = action.round_num
            if r not in round_data:
                round_data[r] = {'round_num': r, 'twitter': 0, 'reddit': 0, 'total': 0}
            round_data[r]['total'] += 1
            if action.platform == 'twitter':
                round_data[r]['twitter'] += 1
            else:
                round_data[r]['reddit'] += 1

        by_round = [round_data[k] for k in sorted(round_data.keys())]

        return {
            'by_type': dict(by_type),
            'by_platform': {p: dict(c) for p, c in by_platform.items()},
            'by_round': by_round,
        }

    def get_engagement_metrics(self, simulation_id: str) -> Dict[str, Any]:
        """
        参与度指标

        Returns:
            {
                total_engagement, avg_engagement_per_post,
                top_agents: [{agent_name, total_actions, posts, engagement}],
                engagement_by_type: {type: count},
            }
        """
        actions = SimulationRunner.get_all_actions(simulation_id, limit=50000)
        if not actions:
            return {'total_engagement': 0, 'avg_engagement_per_post': 0, 'top_agents': [], 'engagement_by_type': {}}

        total_posts = sum(1 for a in actions if a.action_type == 'CREATE_POST')
        engagement_by_type = Counter(a.action_type for a in actions if a.action_type in ENGAGEMENT_ACTION_TYPES)
        total_engagement = sum(engagement_by_type.values())

        # Top agents
        agent_data: Dict[str, Dict] = {}
        for action in actions:
            name = action.agent_name
            if name not in agent_data:
                agent_data[name] = {'agent_name': name, 'total_actions': 0, 'posts': 0, 'engagement': 0}
            agent_data[name]['total_actions'] += 1
            if action.action_type == 'CREATE_POST':
                agent_data[name]['posts'] += 1
            elif action.action_type in ENGAGEMENT_ACTION_TYPES:
                agent_data[name]['engagement'] += 1

        top_agents = sorted(agent_data.values(), key=lambda x: x['total_actions'], reverse=True)[:10]

        return {
            'total_engagement': total_engagement,
            'avg_engagement_per_post': round(total_engagement / max(total_posts, 1), 1),
            'top_agents': top_agents,
            'engagement_by_type': dict(engagement_by_type),
        }

    def get_sentiment_breakdown(self, simulation_id: str) -> Dict[str, Any]:
        """
        情感分布（基于关键词的分类）

        Returns:
            {positive_count, negative_count, neutral_count, positive_ratio, negative_ratio}
        """
        actions = SimulationRunner.get_all_actions(simulation_id, limit=50000)
        if not actions:
            return {'positive_count': 0, 'negative_count': 0, 'neutral_count': 0, 'positive_ratio': 0, 'negative_ratio': 0}

        positive_count = 0
        negative_count = 0
        neutral_count = 0

        for action in actions:
            if action.action_type not in CONTENT_ACTION_TYPES:
                continue
            content = action.action_args.get('content', '')
            if not content:
                continue

            text_lower = content.lower()
            pos_score = sum(1 for kw in POSITIVE_KEYWORDS if kw in text_lower)
            neg_score = sum(1 for kw in NEGATIVE_KEYWORDS if kw in text_lower)

            if pos_score > neg_score:
                positive_count += 1
            elif neg_score > pos_score:
                negative_count += 1
            else:
                neutral_count += 1

        total = positive_count + negative_count + neutral_count
        return {
            'positive_count': positive_count,
            'negative_count': negative_count,
            'neutral_count': neutral_count,
            'positive_ratio': round(positive_count / max(total, 1) * 100, 1),
            'negative_ratio': round(negative_count / max(total, 1) * 100, 1),
            'neutral_ratio': round(neutral_count / max(total, 1) * 100, 1),
        }

    def get_infographic_data(self, simulation_id: str) -> Dict[str, Any]:
        """
        聚合所有数据，生成前端信息图所需的完整 JSON

        Returns:
            {key_metrics, action_distribution, sentiment_breakdown, top_posts, top_agents, timeline}
        """
        overview = self.get_overview_stats(simulation_id)
        distribution = self.get_action_distribution(simulation_id)
        sentiment = self.get_sentiment_breakdown(simulation_id)
        top_posts = self.get_top_posts(simulation_id, n=5)
        engagement = self.get_engagement_metrics(simulation_id)

        return {
            'key_metrics': {
                'total_agents': overview['total_agents'],
                'total_posts': overview['total_posts'],
                'total_engagement': overview['total_engagement'],
                'avg_activity': overview['avg_activity_per_agent'],
                'total_rounds': overview['total_rounds'],
                'total_actions': overview['total_actions'],
            },
            'action_distribution': distribution,
            'sentiment_breakdown': sentiment,
            'top_posts': top_posts,
            'top_agents': engagement.get('top_agents', [])[:5],
            'timeline': distribution.get('by_round', []),
        }

    def get_analytics(self, simulation_id: str, query_type: str, n: int = 10) -> Dict[str, Any]:
        """
        统一入口，供 ReportAgent 工具调用

        Args:
            simulation_id: 模拟ID
            query_type: overview_stats | top_posts | agent_quotes | action_distribution | engagement_metrics | sentiment_breakdown | infographic_data
            n: 返回数量（仅对 top_posts 和 agent_quotes 有效）
        """
        try:
            if query_type == 'overview_stats':
                return {'success': True, 'data': self.get_overview_stats(simulation_id)}
            elif query_type == 'top_posts':
                return {'success': True, 'data': self.get_top_posts(simulation_id, n=n)}
            elif query_type == 'agent_quotes':
                result = self.get_agent_quotes(simulation_id, n_positive=n, n_negative=n, n_random=n)
                return {'success': True, 'data': result}
            elif query_type == 'action_distribution':
                return {'success': True, 'data': self.get_action_distribution(simulation_id)}
            elif query_type == 'engagement_metrics':
                return {'success': True, 'data': self.get_engagement_metrics(simulation_id)}
            elif query_type == 'sentiment_breakdown':
                return {'success': True, 'data': self.get_sentiment_breakdown(simulation_id)}
            elif query_type == 'infographic_data':
                return {'success': True, 'data': self.get_infographic_data(simulation_id)}
            else:
                return {'success': False, 'error': f'Unknown query_type: {query_type}'}
        except Exception as e:
            logger.error(f'Analytics query failed: {e}')
            return {'success': False, 'error': str(e)}

    # ── helpers ──

    def _empty_overview(self) -> Dict[str, Any]:
        return {
            'total_agents': 0, 'total_actions': 0, 'total_rounds': 0,
            'total_posts': 0, 'twitter_posts': 0, 'reddit_posts': 0,
            'total_engagement': 0, 'avg_activity_per_agent': 0,
            'action_type_counts': {}, 'platform_breakdown': {},
        }

    def _deduplicate_and_sample(
        self,
        items: List[Dict[str, Any]],
        n: int,
    ) -> List[Dict[str, Any]]:
        """去重（按 quote 前80字符）并采样"""
        seen = set()
        unique = []
        for item in items:
            key = item['quote'][:80]
            if key not in seen:
                seen.add(key)
                unique.append(item)

        if len(unique) <= n:
            return unique
        return random.sample(unique, n)
